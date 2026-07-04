"""支付截图 AI 自动审核引擎

流程：
1. 对截图进行 OCR 文字提取
2. 将提取的文字 + 订单信息发送给 DeepSeek 进行判断
3. DeepSeek 返回审核结论：approved / rejected / needs_review
"""

from __future__ import annotations

import structlog
from dataclasses import dataclass

from ..utils.llm_client import llm_client

logger = structlog.get_logger(__name__)

AUDIT_SYSTEM_PROMPT = """你是支付审核专家。我会给你一张支付截图的 OCR 识别结果和订单信息，请分析并返回 JSON。

## 分析要点
1. OCR 文字中是否包含支付/转账相关关键词（支付成功、已转账、交易成功、付款金额等）？
2. OCR 中提取到的金额是否与订单期望金额匹配？
3. OCR 文字是否是有效的支付凭证（不是无关内容、不是乱码）？

## 输出格式（严格 JSON）
{
  "is_payment_related": true/false,
  "extracted_amount": "4.99",
  "amount_match": true/false,
  "confidence": 0.85,
  "issues": [],
  "verdict": "approved|rejected|needs_review"
}

## 判定规则
- is_payment_related=true 且 amount_match=true 且 confidence>=0.7 → approved
- is_payment_related=false 或 金额明显不匹配 → rejected
- 其他情况 → needs_review
"""


def _try_ocr(image_path: str) -> str:
    """从截图中提取文字。优先用 pytesseract，fallback 用内置 PIL 像素检测。"""
    # 尝试 pytesseract
    try:
        from PIL import Image
        import pytesseract
        img = Image.open(image_path)
        text = pytesseract.image_to_string(img, lang="chi_sim+eng")
        if text.strip():
            return text.strip()
    except ImportError:
        pass
    except Exception as e:
        logger.debug(f"pytesseract OCR failed: {e}")

    # 尝试 easyocr
    try:
        import easyocr
        reader = easyocr.Reader(["ch_sim", "en"], gpu=False)
        results = reader.readtext(image_path)
        text = " ".join(r[1] for r in results)
        if text.strip():
            return text.strip()
    except ImportError:
        pass
    except Exception as e:
        logger.debug(f"easyocr OCR failed: {e}")

    # fallback: PIL 读取图片基本信息
    try:
        from PIL import Image
        img = Image.open(image_path)
        info = f"[图片基本信息] 尺寸={img.size} 格式={img.format} 模式={img.mode}"
        # 纯色检测：密集采样网格，检查像素变化
        if img.mode == "RGB":
            w, h = img.size
            step = max(w, h) // 40  # 约 40 个采样点
            r_vals, g_vals, b_vals = [], [], []
            for x in range(0, w, step):
                for y in range(0, h, step):
                    px = img.getpixel((x, y))
                    r_vals.append(px[0])
                    g_vals.append(px[1])
                    b_vals.append(px[2])
            r_range = max(r_vals) - min(r_vals)
            g_range = max(g_vals) - min(g_vals)
            b_range = max(b_vals) - min(b_vals)
            if r_range < 5 and g_range < 5 and b_range < 5:
                return info + " [警告：图片可能为纯色或简单图案]"
        return info
    except Exception:
        return "[无法读取图片信息]"


@dataclass
class AuditResult:
    verdict: str           # "approved" | "rejected" | "needs_review"
    message: str
    extracted_amount: str | None = None
    confidence: float = 0.0
    issues: list[str] | None = None


class PaymentAuditor:
    """支付截图 AI 审核器"""

    async def audit(
        self,
        proof_path: str,
        order_amount_cents: int,
        order_subject: str,
    ) -> AuditResult:
        expected_amount = f"{order_amount_cents / 100:.2f}"

        # Step 1: OCR 提取文字
        ocr_text = _try_ocr(proof_path)
        logger.info(f"payment_audit_ocr len={len(ocr_text)}")

        # Step 2: 快速硬规则检查
        # 纯色/空图片检测
        if "[警告：图片可能为纯色或简单图案]" in ocr_text:
            return AuditResult(
                verdict="rejected",
                message="检测到上传的不是有效截图（可能为纯色图片），AI 自动拒绝。请上传真实的支付截图。",
                confidence=0.0,
                issues=["上传的图片为纯色或简单图案，非有效支付凭证"],
            )

        # 尺寸过小检测
        try:
            from PIL import Image
            img = Image.open(proof_path)
            if img.size[0] < 50 or img.size[1] < 50:
                return AuditResult(
                    verdict="rejected",
                    message="图片尺寸过小，AI 自动拒绝。请上传清晰的支付截图。",
                    confidence=0.0,
                    issues=["图片尺寸过小，无法识别"],
                )
        except Exception:
            pass

        # Step 3: DeepSeek 文本分析
        user_prompt = f"""请分析以下支付凭证的 OCR 识别结果。期望金额为 ¥{expected_amount}。

订单信息：{order_subject}

OCR 识别文字：
```
{ocr_text[:3000]}
```

请返回 JSON 判定结果。"""

        try:
            resp = await llm_client.chat_json(
                system=AUDIT_SYSTEM_PROMPT,
                user=user_prompt,
                temperature=0.1,
                max_tokens=512,
            )

            verdict = resp.get("verdict", "needs_review")
            confidence = resp.get("confidence", 0.0)
            extracted = resp.get("extracted_amount")
            amount_match = resp.get("amount_match", False)
            is_payment = resp.get("is_payment_related", False)
            issues = resp.get("issues") or []

            # 硬规则二次校验
            if verdict == "approved" and not is_payment:
                verdict = "rejected"
                issues.append("OCR 内容不包含支付相关信息")
            if verdict == "approved" and not amount_match:
                verdict = "rejected"
                issues.append("金额不匹配")

            # OCR 为空但非图片异常的降级
            if not ocr_text.strip() or ocr_text.startswith("[图片基本信息]"):
                verdict = "needs_review"
                issues.append("OCR 未能提取到有效文字，转人工审核")

            logger.info(
                f"payment_audit_done verdict={verdict} confidence={confidence} "
                f"amount_match={amount_match} is_payment={is_payment}"
            )

            return AuditResult(
                verdict=verdict,
                message=self._msg(verdict, issues, expected_amount),
                extracted_amount=extracted,
                confidence=confidence,
                issues=issues,
            )

        except Exception as e:
            logger.warning(f"payment_audit_llm_failed error={e}")
            return AuditResult(
                verdict="needs_review",
                message="AI 审核服务暂时不可用，已转入人工审核队列。",
                confidence=0.0,
                issues=[str(e)],
            )

    def _msg(self, verdict: str, issues: list[str], expected: str) -> str:
        if verdict == "approved":
            return "AI 审核通过：支付凭证验证成功，权益已自动发放。"
        if verdict == "rejected":
            detail = "; ".join(issues) if issues else "凭证验证未通过"
            return f"AI 审核未通过：{detail}。请确认已支付 ¥{expected} 后重新上传有效截图。"
        return "AI 无法自动判定（OCR 识别不完整），已转入人工审核队列。"


_auditor: PaymentAuditor | None = None


def get_payment_auditor() -> PaymentAuditor:
    global _auditor
    if _auditor is None:
        _auditor = PaymentAuditor()
    return _auditor
