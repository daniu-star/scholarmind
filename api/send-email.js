/**
 * Vercel Serverless Function — 邮件代理
 *
 * 通过 nodemailer + SMTP 发送验证码邮件，绕过 Railway 的 SMTP 端口封锁。
 * Vercel/AWS Lambda 不封锁 SMTP 465/587 端口。
 *
 * 认证：X-API-Key 请求头需匹配环境变量 EMAIL_PROXY_KEY
 * 调用：POST /api/send-email  body: { to_email, code }
 */
const nodemailer = require('nodemailer');

// 缓存 transporter（serverless 冷启动优化，避免每次请求都创建连接）
let transporter = null;

function getTransporter() {
  if (!transporter) {
    const host = process.env.SMTP_HOST || 'smtp.163.com';
    const port = parseInt(process.env.SMTP_PORT || '465', 10);
    transporter = nodemailer.createTransport({
      host: host,
      port: port,
      secure: port === 465, // 465 用 SSL 直连，587 用 STARTTLS
      auth: {
        user: process.env.SMTP_USER,
        pass: process.env.SMTP_PASSWORD,
      },
      connectionTimeout: 8000,
      greetingTimeout: 5000,
      socketTimeout: 8000,
    });
  }
  return transporter;
}

module.exports = async (req, res) => {
  // CORS 预检
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, X-API-Key');

  if (req.method === 'OPTIONS') {
    return res.status(204).end();
  }

  if (req.method !== 'POST') {
    return res.status(405).json({ success: false, error: 'Method not allowed' });
  }

  // 密钥认证（防止外部滥用）
  const apiKey = req.headers['x-api-key'];
  if (!apiKey || apiKey !== process.env.EMAIL_PROXY_KEY) {
    return res.status(401).json({ success: false, error: 'Unauthorized' });
  }

  const { to_email, code } = req.body || {};

  if (!to_email || !code) {
    return res.status(400).json({ success: false, error: 'Missing to_email or code' });
  }

  // 基本邮箱格式校验
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(to_email)) {
    return res.status(400).json({ success: false, error: 'Invalid email format' });
  }

  try {
    const t = getTransporter();
    const fromName = process.env.SMTP_FROM_NAME || 'ScholarMind';
    const fromEmail = process.env.SMTP_USER;
    const expireMinutes = process.env.VERIFICATION_CODE_EXPIRE_MINUTES || '5';

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

    const info = await t.sendMail({
      from: `"${fromName}" <${fromEmail}>`,
      to: to_email,
      subject: `[ScholarMind] 验证码：${code}`,
      html: html,
      replyTo: fromEmail,
    });

    console.log('email_sent_success', { to: to_email, messageId: info.messageId });
    return res.status(200).json({ success: true, message_id: info.messageId });
  } catch (error) {
    console.error('send-email error:', error.message);
    return res.status(500).json({ success: false, error: error.message });
  }
};
