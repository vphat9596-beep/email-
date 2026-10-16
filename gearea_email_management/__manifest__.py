# -*- coding: utf-8 -*-
{
    'name': 'Gearea Email Management',
    'version': '16.0.1.0.0',
    'category': 'Marketing/Email Marketing',
    'summary': 'Giới hạn gửi mail cá nhân (Phương án B) và ép chiến dịch hàng loạt qua Dedicated Server (Phương án C)',
    'description': """
Gearea Email Management
=======================
Phương án B - Gửi từng email:
    * Giới hạn số email gửi từ hộp thư cá nhân (Gmail/Outlook) theo chu kỳ,
      chu kỳ lấy từ tham số hệ thống ``mail.server.personal.limit.minutes``.
    * Hiển thị mức sử dụng trong Preferences của người dùng.

Phương án C - Gửi hàng loạt:
    * Bắt buộc chiến dịch Email Marketing đi qua Dedicated Server
      (Amazon SES / Brevo, dùng tên miền phụ).
    * Kiểm tra email hợp lệ trước khi đưa vào hàng đợi (chặn nếu email hỏng > 2%).
    """,
    'author': 'Gearea',
    'website': 'https://geareademo.sge.vn',
    'license': 'LGPL-3',
    'depends': ['base', 'mail', 'crm', 'mass_mailing'],
    'data': [
        'views/res_users_views.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
