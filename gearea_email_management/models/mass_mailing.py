# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models, tools, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

# Tham số hệ thống dùng trong module
PARAM_ENFORCE = 'gearea.mass_mailing.enforce_dedicated'          # 'True'/'False' (mặc định True)
PARAM_ALLOWED_HOSTS = 'gearea.mass_mailing.allowed_smtp_hosts'   # danh sách đuôi host, cách nhau dấu phẩy
PARAM_SENDER_DOMAIN = 'gearea.mass_mailing.sender_domain'        # tên miền phụ bắt buộc, ví dụ mail.gearea.vn
PARAM_MAX_INVALID = 'gearea.mass_mailing.max_invalid_percent'    # mặc định 2.0

DEFAULT_ALLOWED_HOSTS = 'amazonaws.com,brevo.com,sendinblue.com'
DEFAULT_MAX_INVALID = 2.0
BATCH_SIZE = 5000


class MailingMailing(models.Model):
    _inherit = 'mailing.mailing'

    # Kết quả kiểm tra gần nhất (ghi khi kiểm tra đạt)
    gearea_total_recipients = fields.Integer(
        string='Tổng người nhận (đã kiểm tra)', readonly=True, copy=False)
    gearea_invalid_count = fields.Integer(
        string='Số email không hợp lệ', readonly=True, copy=False)
    gearea_invalid_ratio = fields.Float(
        string='Tỷ lệ email hỏng (%)', digits=(5, 2), readonly=True, copy=False)

    # ------------------------------------------------------------------
    # Đọc cấu hình
    # ------------------------------------------------------------------
    @api.model
    def _gearea_param(self, key, default=None):
        return self.env['ir.config_parameter'].sudo().get_param(key, default)

    @api.model
    def _gearea_is_enforced(self):
        return str(self._gearea_param(PARAM_ENFORCE, 'True')).lower() not in ('false', '0', '')

    @api.model
    def _gearea_get_dedicated_server(self):
        """Dedicated Server khai báo ở Settings > Email Marketing (tham số mass_mailing.mail_server_id)."""
        value = self._gearea_param('mass_mailing.mail_server_id')
        if not value:
            return self.env['ir.mail_server']
        try:
            return self.env['ir.mail_server'].sudo().browse(int(value)).exists()
        except (TypeError, ValueError):
            return self.env['ir.mail_server']

    # ------------------------------------------------------------------
    # Ép luồng gửi qua Dedicated Server
    # ------------------------------------------------------------------
    def _gearea_enforce_dedicated_server(self):
        if not self._gearea_is_enforced():
            return
        outgoing_enabled = str(self._gearea_param('mass_mailing.outgoing_mail_server', 'False')).lower() \
            not in ('false', '0', '')
        server = self._gearea_get_dedicated_server()
        if not outgoing_enabled or not server:
            raise UserError(_(
                'Chiến dịch gửi hàng loạt bắt buộc dùng Dedicated Server (Amazon SES/Brevo). '
                'Vui lòng vào Cài đặt > Email Marketing, bật "Dedicated Server" và chọn máy chủ SMTP riêng.'))
        if not server.active:
            raise UserError(_('Dedicated Server "%s" đang bị lưu trữ (inactive).', server.name))

        # Chỉ cho phép host SMTP thuộc dịch vụ chuyên dụng đã khai báo
        allowed = [h.strip().lower() for h in
                   self._gearea_param(PARAM_ALLOWED_HOSTS, DEFAULT_ALLOWED_HOSTS).split(',') if h.strip()]
        host = (server.smtp_host or '').lower()
        if allowed and not any(host.endswith(suffix) for suffix in allowed):
            raise UserError(_(
                'Máy chủ SMTP "%(host)s" không thuộc danh sách dịch vụ gửi hàng loạt cho phép (%(allowed)s). '
                'Không được gửi chiến dịch qua máy chủ email công ty.',
                host=server.smtp_host, allowed=', '.join(allowed)))

        sender_domain = (self._gearea_param(PARAM_SENDER_DOMAIN) or '').strip().lower()
        for mailing in self:
            # Ép chiến dịch dùng đúng Dedicated Server
            if mailing.mail_server_id != server:
                mailing.mail_server_id = server
            # Địa chỉ người gửi phải thuộc tên miền phụ (bảo vệ tên miền chính của công ty)
            if sender_domain:
                email_from = tools.email_normalize(mailing.email_from) or ''
                if not email_from.endswith('@' + sender_domain):
                    raise UserError(_(
                        'Địa chỉ người gửi chiến dịch phải thuộc tên miền phụ @%(domain)s '
                        '(hiện tại: %(current)s).',
                        domain=sender_domain, current=mailing.email_from or _('trống')))

    # ------------------------------------------------------------------
    # Kiểm tra email hợp lệ trước khi vào hàng đợi
    # ------------------------------------------------------------------
    def _gearea_get_email_fields(self, model):
        """Lấy tên trường email chính của model đích."""
        primary = getattr(model, '_primary_email', None) or 'email'
        if isinstance(primary, str):
            primary = [primary]
        return [f for f in primary if f in model._fields]

    def _gearea_validate_recipients(self):
        max_percent = float(self._gearea_param(PARAM_MAX_INVALID, DEFAULT_MAX_INVALID))
        for mailing in self:
            res_ids = mailing._get_remaining_recipients()
            total = len(res_ids)
            if not total:
                continue
            Model = self.env[mailing.mailing_model_real]
            email_fields = self._gearea_get_email_fields(Model)
            if not email_fields:
                _logger.info('Chiến dịch %s: model %s không có trường email, bỏ qua kiểm tra.',
                             mailing.id, Model._name)
                continue

            invalid = 0
            samples = []
            for start in range(0, total, BATCH_SIZE):
                records = Model.browse(res_ids[start:start + BATCH_SIZE])
                for rec in records:
                    value = next((rec[f] for f in email_fields if rec[f]), False)
                    # email_normalize trả về False nếu rỗng hoặc không đúng định dạng
                    if not value or not tools.email_normalize(value):
                        invalid += 1
                        if len(samples) < 5:
                            samples.append('%s (ID %s)' % (value or _('trống'), rec.id))

            ratio = invalid * 100.0 / total
            if ratio > max_percent:
                raise ValidationError(_(
                    'Không thể đưa chiến dịch "%(name)s" vào hàng đợi: có %(invalid)s/%(total)s email '
                    'không hợp lệ (%(ratio).2f%%), vượt ngưỡng cho phép %(max).2f%%.\n'
                    'Ví dụ: %(samples)s\n'
                    'Vui lòng làm sạch danh sách người nhận rồi thử lại.',
                    name=mailing.subject or mailing.display_name,
                    invalid=invalid, total=total, ratio=ratio, max=max_percent,
                    samples='; '.join(samples)))

            mailing.write({
                'gearea_total_recipients': total,
                'gearea_invalid_count': invalid,
                'gearea_invalid_ratio': ratio,
            })

    # ------------------------------------------------------------------
    # Các điểm chặn
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        """Chiến dịch mới tự động gán Dedicated Server nếu có."""
        if self._gearea_is_enforced():
            server = self._gearea_get_dedicated_server()
            if server:
                for vals in vals_list:
                    vals.setdefault('mail_server_id', server.id)
        return super().create(vals_list)

    def action_put_in_queue(self):
        """Mọi đường Gửi ngay / Lên lịch đều đi qua hàm này."""
        self._gearea_enforce_dedicated_server()
        self._gearea_validate_recipients()
        return super().action_put_in_queue()
