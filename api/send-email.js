/**
 * Vercel Serverless Function — 邮件代理
 *
 * 通过 nodemailer + SMTP 发送验证码邮件，绕过 Railway 的 SMTP 端口封锁。
 * Vercel/AWS Lambda 不封锁 SMTP 465/587 端口。
 *
 * 认证：X-API-Key 请求头需匹配 PROXY_API_KEY 常量
 * 调用：POST /api/send-email
 *   headers: { X-API-Key: <proxy_key> }
 *   body: { to_email, code, smtp_host, smtp_port, smtp_user, smtp_password, smtp_from_name }
 *
 * 设计说明：
 *   SMTP 凭据由后端通过 HTTPS 请求体传入（加密传输），不在 Vercel 环境变量中存储。
 *   后端从自身 .env 读取 SMTP_USER/SMTP_PASSWORD，确保真实凭据不入源码仓库。
 */
const nodemailer = require('nodemailer');

module.exports = async (req, res) => {
  if (req.method !== 'POST') {
    return res.status(405).json({ success: false, error: 'Method not allowed' });
  }

  const proxyApiKey = process.env.VERCEL_EMAIL_PROXY_KEY;
  if (!proxyApiKey) {
    return res.status(503).json({ success: false, error: 'Email proxy is not configured' });
  }

  // 密钥必须由 Vercel 环境变量提供，禁止把生产密钥提交到源码。
  const apiKey = req.headers['x-api-key'];
  if (!apiKey || apiKey !== proxyApiKey) {
    return res.status(401).json({ success: false, error: 'Unauthorized' });
  }

  const {
    to_email,
    code,
    smtp_host,
    smtp_port,
    smtp_user,
    smtp_password,
    smtp_from_name,
  } = req.body || {};

  // 参数校验
  if (!to_email || !code) {
    return res.status(400).json({ success: false, error: 'Missing to_email or code' });
  }
  if (!smtp_user || !smtp_password) {
    return res.status(400).json({ success: false, error: 'Missing smtp credentials' });
  }
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(to_email)) {
    return res.status(400).json({ success: false, error: 'Invalid email format' });
  }
  if (!/^\d{4,8}$/.test(String(code))) {
    return res.status(400).json({ success: false, error: 'Invalid code format' });
  }

  const host = smtp_host || 'smtp.163.com';
  const port = parseInt(smtp_port || '465', 10);
  const fromName = smtp_from_name || 'ScholarMind';
  const expireMinutes = '5';

  try {
    // 每次请求创建新 transporter（凭据来自请求体，不可缓存）
    const transporter = nodemailer.createTransport({
      host: host,
      port: port,
      secure: port === 465, // 465 用 SSL 直连，587 用 STARTTLS
      auth: {
        user: smtp_user,
        pass: smtp_password,
      },
      connectionTimeout: 8000,
      greetingTimeout: 5000,
      socketTimeout: 8000,
    });

    const html = `<div style="max-width:480px;margin:0 auto;font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',sans-serif;color:#1a1a1a;background:#f0f7f1;border-radius:16px;padding:36px 28px">
  <div style="text-align:center;margin-bottom:24px">
    <div style="display:inline-block;background:linear-gradient(135deg,#2E7D32,#1B5E20);color:#fff;font-size:28px;font-weight:700;padding:8px 20px;border-radius:10px;letter-spacing:1px">ScholarMind</div>
    <div style="font-size:13px;color:#6b8e6f;margin-top:8px">智能学术研究助手 · 验证码</div>
  </div>
  <div style="background:#fff;border-radius:14px;padding:28px 24px;text-align:center;box-shadow:0 2px 12px rgba(0,0,0,.06)">
    <div style="font-size:15px;color:#4a5b4c;margin-bottom:18px">您的验证码是</div>
    <div style="font-size:42px;font-weight:700;letter-spacing:10px;color:#2E7D32;margin-bottom:18px;font-family:'SF Mono','Consolas','Courier New',monospace">${code}</div>
    <div style="display:inline-block;background:#f0f7f1;color:#5a8a5e;font-size:12px;padding:6px 14px;border-radius:20px;margin-bottom:8px">${expireMinutes} 分钟内有效，请勿泄露</div>
  </div>
  <div style="text-align:center;margin-top:20px;font-size:11px;color:#a0b8a2;line-height:1.6">
    此邮件由 ScholarMind 自动发送<br>如非本人操作，请忽略
  </div>
</div>`;

    const info = await transporter.sendMail({
      from: `"${fromName}" <${smtp_user}>`,
      to: to_email,
      subject: `[ScholarMind] 验证码：${code}`,
      html: html,
      replyTo: smtp_user,
    });

    console.log('email_sent_success', { to: to_email, messageId: info.messageId });
    return res.status(200).json({ success: true, message_id: info.messageId });
  } catch (error) {
    console.error('send-email error:', error.message);
    return res.status(500).json({ success: false, error: error.message });
  }
};
