# -*- coding: utf-8 -*-
import logging
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

# Tham số hệ thống (Settings > Technical > System Parameters)
# Chu kỳ (phút) dùng để tính giới hạn gửi mail cá nhân.
PARAM_LIMIT_MINUTES = 'mail.server.personal.limit.minutes'
# Số email tối đa mỗi chu kỳ áp dụng mặc định cho nhân sự chưa cấu hình riêng.
PARAM_DEFAULT_LIMIT = 'gearea.mail.personal.default_limit'

DEFAULT_LIMIT_MINUTES = 60
DEFAULT_LIMIT_COUNT = 30


class ResUsers(models.Model):
    _inherit = 'res.users'

    # ------------------------------------------------------------------
    # Trường cấu hình (chỉ quản trị viên được sửa) và trường theo dõi
    # ------------------------------------------------------------------
    gearea_mail_limit_count = fields.Integer(
        string='Giới hạn email riêng',
        default=0,
        help='Số email tối đa người dùng được gửi từ hộp thư cá nhân trong mỗi chu kỳ. '
             'Để 0 để dùng mức mặc định của hệ thống.',
    )
    gearea_mail_limit_minutes = fields.Integer(
        string='Chu kỳ giới hạn (phút)',
        compute='_compute_gearea_mail_usage',
    )
    gearea_mail_effective_limit = fields.Integer(
        string='Giới hạn áp dụng',
        compute='_compute_gearea_mail_usage',
    )
    gearea_mail_sent_in_window = fields.Integer(
        string='Đã gửi trong chu kỳ',
        compute='_compute_gearea_mail_usage',
    )
    gearea_mail_remaining = fields.Integer(
        string='Còn lại',
        compute='_compute_gearea_mail_usage',
    )
    gearea_mail_usage_percent = fields.Float(
        string='Mức sử dụng (%)',
        compute='_compute_gearea_mail_usage',
    )

    # ------------------------------------------------------------------
    # Cho phép người dùng ĐỌC (không sửa) các trường này trong Preferences
    # ------------------------------------------------------------------
    @property
    def SELF_READABLE_FIELDS(self):
        return super().SELF_READABLE_FIELDS + [
            'gearea_mail_limit_count',
            'gearea_mail_limit_minutes',
            'gearea_mail_effective_limit',
            'gearea_mail_sent_in_window',
            'gearea_mail_remaining',
            'gearea_mail_usage_percent',
        ]

    # ------------------------------------------------------------------
    # Ràng buộc
    # ------------------------------------------------------------------
    @api.constrains('gearea_mail_limit_count')
    def _check_gearea_mail_limit_count(self):
        for user in self:
            if user.gearea_mail_limit_count < 0:
                raise ValidationError(_('Giới hạn email riêng không được là số âm.'))

    # ------------------------------------------------------------------
    # Hàm tiện ích đọc cấu hình
    # ------------------------------------------------------------------
    @api.model
    def _gearea_get_window_minutes(self):
        """Đọc chu kỳ (phút) từ tham số hệ thống, mặc định 60 phút."""
        value = self.env['ir.config_parameter'].sudo().get_param(
            PARAM_LIMIT_MINUTES, default=str(DEFAULT_LIMIT_MINUTES))
        try:
            minutes = int(value)
        except (TypeError, ValueError):
            _logger.warning('Giá trị %s không hợp lệ: %r, dùng mặc định %s phút.',
                            PARAM_LIMIT_MINUTES, value, DEFAULT_LIMIT_MINUTES)
            return DEFAULT_LIMIT_MINUTES
        return minutes if minutes > 0 else DEFAULT_LIMIT_MINUTES

    @api.model
    def _gearea_get_default_limit(self):
        value = self.env['ir.config_parameter'].sudo().get_param(
            PARAM_DEFAULT_LIMIT, default=str(DEFAULT_LIMIT_COUNT))
        try:
            return max(int(value), 0)
        except (TypeError, ValueError):
            return DEFAULT_LIMIT_COUNT

    def _gearea_get_effective_limit(self):
        """Giới hạn áp dụng: cấu hình riêng nếu > 0, ngược lại dùng mặc định hệ thống."""
        self.ensure_one()
        return self.gearea_mail_limit_count or self._gearea_get_default_limit()

    # ------------------------------------------------------------------
    # Tính toán mức sử dụng
    # ------------------------------------------------------------------
    @api.depends('gearea_mail_limit_count')
    def _compute_gearea_mail_usage(self):
        minutes = self._gearea_get_window_minutes()
        since = fields.Datetime.now() - timedelta(minutes=minutes)
        MailMail = self.env['mail.mail'].sudo()
        for user in self:
            limit = user._gearea_get_effective_limit()
            sent = 0
            # user.id có thể là NewId khi đang tạo mới trên form -> bỏ qua
            if isinstance(user.id, int) and user.partner_id:
                sent = MailMail.search_count([
                    ('author_id', '=', user.partner_id.id),
                    ('mailing_id', '=', False),  # loại trừ mail hàng loạt (Phương án C)
                    ('state', 'in', ('outgoing', 'sent')),
                    ('date', '>=', since),
                ])
            user.gearea_mail_limit_minutes = minutes
            user.gearea_mail_effective_limit = limit
            user.gearea_mail_sent_in_window = sent
            user.gearea_mail_remaining = max(limit - sent, 0)
            user.gearea_mail_usage_percent = min(sent * 100.0 / limit, 100.0) if limit else 0.0

    # ------------------------------------------------------------------
    # API kiểm tra - có thể gọi từ nơi khác trước khi gửi mail cá nhân
    # ------------------------------------------------------------------
    def gearea_check_personal_limit(self, to_send=1):
        """Ném UserError nếu gửi thêm `to_send` email sẽ vượt giới hạn chu kỳ."""
        self.ensure_one()
        limit = self._gearea_get_effective_limit()
        if not limit:
            return True
        # Đọc lại từ DB để số liệu mới nhất
        self.invalidate_recordset(['gearea_mail_sent_in_window'])
        if self.gearea_mail_sent_in_window + to_send > limit:
            raise UserError(_(
                'Bạn đã đạt giới hạn gửi email cá nhân: tối đa %(limit)s email mỗi %(minutes)s phút '
                '(đã gửi %(sent)s). Vui lòng thử lại sau.',
                limit=limit,
                minutes=self.gearea_mail_limit_minutes,
                sent=self.gearea_mail_sent_in_window,
            ))
        return True
