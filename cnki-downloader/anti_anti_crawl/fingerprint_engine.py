"""Dynamic browser fingerprint randomization for anti-detection.

Injects JS to randomize canvas, WebGL, fonts, and navigator properties
that CNKI's anti-bot system uses for fingerprinting.
"""

from __future__ import annotations

import structlog
import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page, BrowserContext

logger = structlog.get_logger()

# ═══════════════════════════════════════════════════════════════
# Canvas Fingerprint Randomization
# ═══════════════════════════════════════════════════════════════

CANVAS_NOISE_SCRIPT = """
// Add subtle noise to canvas toDataURL output
(function() {
    const originalToDataURL = HTMLCanvasElement.prototype.toDataURL;
    HTMLCanvasElement.prototype.toDataURL = function(...args) {
        const ctx = this.getContext('2d', { willReadFrequently: true });
        if (ctx) {
            const imageData = ctx.getImageData(0, 0, Math.min(this.width, 50), Math.min(this.height, 50));
            for (let i = 0; i < imageData.data.length; i += 4) {
                // Add ±1 noise to RGB channels of first few pixels
                if (Math.random() < 0.3) {
                    const noise = Math.random() < 0.5 ? 1 : -1;
                    imageData.data[i] = Math.min(255, Math.max(0, imageData.data[i] + noise));
                    imageData.data[i + 1] = Math.min(255, Math.max(0, imageData.data[i + 1] + noise));
                    imageData.data[i + 2] = Math.min(255, Math.max(0, imageData.data[i + 2] + noise));
                }
            }
            ctx.putImageData(imageData, 0, 0);
        }
        return originalToDataURL.apply(this, args);
    };
})();
"""

# ═══════════════════════════════════════════════════════════════
# WebGL Fingerprint Randomization
# ═══════════════════════════════════════════════════════════════

WEBGL_NOISE_SCRIPT = """
// Randomize WebGL vendor/renderer strings
(function() {
    const getParameterProxies = new WeakMap();

    function createProxy(gl) {
        if (getParameterProxies.has(gl)) return gl;

        const originalGetParameter = gl.getParameter.bind(gl);
        const vendorStrings = [
            'Google Inc. (NVIDIA)', 'Google Inc. (Intel)', 'Google Inc. (AMD)',
            'Google Inc. (Qualcomm)', 'Google Inc. (Apple)'
        ];
        const rendererStrings = [
            'ANGLE (NVIDIA GeForce RTX 3060)', 'ANGLE (Intel UHD Graphics 630)',
            'ANGLE (AMD Radeon RX 580)', 'ANGLE (NVIDIA GeForce GTX 1660)',
            'ANGLE (Intel Iris Xe Graphics)'
        ];
        const randomVendor = vendorStrings[Math.floor(Math.random() * vendorStrings.length)];
        const randomRenderer = rendererStrings[Math.floor(Math.random() * rendererStrings.length)];

        gl.getParameter = function(pname) {
            // UNMASKED_VENDOR_WEBGL = 37445
            if (pname === 37445) return randomVendor;
            // UNMASKED_RENDERER_WEBGL = 37446
            if (pname === 37446) return randomRenderer;
            return originalGetParameter(pname);
        };

        getParameterProxies.set(gl, true);
        return gl;
    }

    const originalGetContext = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function(...args) {
        const ctx = originalGetContext.apply(this, args);
        if (args[0] && args[0].includes('webgl')) {
            createProxy(ctx);
        }
        return ctx;
    };
})();
"""

# ═══════════════════════════════════════════════════════════════
# Font Fingerprint Randomization
# ═══════════════════════════════════════════════════════════════

FONT_NOISE_SCRIPT = """
// Return randomized Chinese-capable font list
(function() {
    const baseFonts = [
        'Arial', 'Times New Roman', 'Courier New', 'Georgia', 'Verdana',
        'SimSun', 'SimHei', 'Microsoft YaHei', 'KaiTi', 'FangSong',
        'NSimSun', 'STSong', 'STKaiti', 'STHeiti', 'STFangsong',
        'WenQuanYi Micro Hei', 'WenQuanYi Zen Hei', 'Noto Sans CJK SC',
        'Source Han Sans SC', 'Source Han Serif SC'
    ];

    if (document.fonts && document.fonts.entries) {
        const originalEntries = document.fonts.entries;
        document.fonts.entries = function() {
            return originalEntries.call(this);
        };

        const originalValues = document.fonts.values;
        document.fonts.values = function() {
            return originalValues.call(this);
        };
    }
})();
"""

# ═══════════════════════════════════════════════════════════════
# Screen/Viewport Randomization
# ═══════════════════════════════════════════════════════════════

SCREEN_NOISE_SCRIPT = """
(function() {
    // Randomize screen dimensions slightly
    const screens = [
        { width: 1366, height: 768, availWidth: 1366, availHeight: 728 },
        { width: 1440, height: 900, availWidth: 1440, availHeight: 860 },
        { width: 1536, height: 864, availWidth: 1536, availHeight: 824 },
        { width: 1920, height: 1080, availWidth: 1920, availHeight: 1040 },
    ];
    const s = screens[Math.floor(Math.random() * screens.length)];

    Object.defineProperty(screen, 'width', { get: () => s.width });
    Object.defineProperty(screen, 'height', { get: () => s.height });
    Object.defineProperty(screen, 'availWidth', { get: () => s.availWidth });
    Object.defineProperty(screen, 'availHeight', { get: () => s.availHeight });
    Object.defineProperty(screen, 'colorDepth', { get: () => 24 });
    Object.defineProperty(screen, 'pixelDepth', { get: () => 24 });
})();
"""

# ═══════════════════════════════════════════════════════════════
# WebRTC Leak Prevention
# ═══════════════════════════════════════════════════════════════

WEBRTC_BLOCK_SCRIPT = """
// Disable WebRTC to prevent IP leaks
(function() {
    const noop = () => {};
    if (window.RTCPeerConnection) {
        const orig = window.RTCPeerConnection;
        window.RTCPeerConnection = function(...args) {
            const pc = new orig(...args);
            pc.createDataChannel = noop;
            pc.createOffer = (...a) => orig.prototype.createOffer.apply(pc, a);
            return pc;
        };
        window.RTCPeerConnection.prototype = orig.prototype;
    }
})();
"""

# ═══════════════════════════════════════════════════════════════
# Engine
# ═══════════════════════════════════════════════════════════════

ALL_FINGERPRINT_SCRIPTS = [
    CANVAS_NOISE_SCRIPT,
    WEBGL_NOISE_SCRIPT,
    FONT_NOISE_SCRIPT,
    SCREEN_NOISE_SCRIPT,
    WEBRTC_BLOCK_SCRIPT,
]


class FingerprintEngine:
    """Manages browser fingerprint randomization."""

    def __init__(self):
        self._randomization_count = 0

    async def randomize_all(self, page: "Page") -> None:
        """Inject all fingerprint randomization scripts into the page."""
        for script in ALL_FINGERPRINT_SCRIPTS:
            try:
                await page.evaluate(script)
            except Exception as e:
                logger.debug("fingerprint_script_failed", error=str(e)[:100])

        # Additional dynamic navigator randomization
        await self._randomize_navigator(page)
        self._randomization_count += 1
        logger.debug("fingerprint_randomized", count=self._randomization_count)

    async def _randomize_navigator(self, page: "Page") -> None:
        """Randomize navigator properties dynamically."""
        script = f"""
        (function() {{
            Object.defineProperty(navigator, 'maxTouchPoints', {{ get: () => {random.choice([0, 1, 5])} }});
            Object.defineProperty(navigator, 'platform', {{ get: () => '{random.choice(["Win32", "Win64"])}' }});
        }})();
        """
        try:
            await page.evaluate(script)
        except Exception:
            pass

    async def randomize_on_suspicion(self, page: "Page") -> None:
        """Re-randomize when suspicious activity is detected by rhythm_detector."""
        await self.randomize_all(page)
        # Force a small delay after randomization
        import asyncio
        await asyncio.sleep(random.uniform(0.5, 2.0))
        logger.info("fingerprint_rerandomized_on_suspicion")


# Global singleton
fingerprint_engine = FingerprintEngine()
