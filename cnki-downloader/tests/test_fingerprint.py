"""Tests for fingerprint engine and anti-anti-crawl modules (unit tests)."""

import pytest


class TestFingerprintScripts:
    """Tests that fingerprint randomization scripts are valid JS."""

    def test_canvas_noise_script_exists(self):
        from anti_anti_crawl.fingerprint_engine import CANVAS_NOISE_SCRIPT
        assert "HTMLCanvasElement" in CANVAS_NOISE_SCRIPT
        assert "toDataURL" in CANVAS_NOISE_SCRIPT

    def test_webgl_noise_script_exists(self):
        from anti_anti_crawl.fingerprint_engine import WEBGL_NOISE_SCRIPT
        assert "getParameter" in WEBGL_NOISE_SCRIPT
        assert "UNMASKED_VENDOR_WEBGL" in WEBGL_NOISE_SCRIPT

    def test_all_scripts_are_strings(self):
        from anti_anti_crawl.fingerprint_engine import ALL_FINGERPRINT_SCRIPTS
        assert len(ALL_FINGERPRINT_SCRIPTS) >= 5
        for script in ALL_FINGERPRINT_SCRIPTS:
            assert isinstance(script, str)
            assert len(script) > 50

    def test_stealth_scripts_valid(self):
        from anti_anti_crawl.browser_manager import STEALTH_SCRIPTS
        assert len(STEALTH_SCRIPTS) >= 5
        for script in STEALTH_SCRIPTS:
            assert isinstance(script, str)


class TestBehaviorSimulator:
    """Tests for behavior simulation."""

    def test_human_delay_poisson(self):
        from anti_anti_crawl.behavior_simulator import behavior_simulator
        delay = behavior_simulator.human_delay(500, 3000, "poisson")
        assert 500 <= delay <= 3000

    def test_human_delay_reading(self):
        from anti_anti_crawl.behavior_simulator import behavior_simulator
        delay = behavior_simulator.human_delay(distribution="reading")
        assert 2000 <= delay <= 8000

    def test_human_delay_click(self):
        from anti_anti_crawl.behavior_simulator import behavior_simulator
        delay = behavior_simulator.human_delay(distribution="click")
        assert 300 <= delay <= 1500

    def test_human_delay_typing(self):
        from anti_anti_crawl.behavior_simulator import behavior_simulator
        delay = behavior_simulator.human_delay(distribution="typing")
        assert 50 <= delay <= 250

    def test_bezier_curve(self):
        from anti_anti_crawl.behavior_simulator import behavior_simulator
        x, y = behavior_simulator._bezier_curve(
            (0, 0), (100, 0), (200, 100), (300, 100), 0.5
        )
        assert 50 <= x <= 250
        assert 0 <= y <= 150


class TestFingerprintEngine:
    """Tests for the FingerprintEngine class."""

    def test_initialization(self):
        from anti_anti_crawl.fingerprint_engine import FingerprintEngine
        engine = FingerprintEngine()
        assert engine._randomization_count == 0


class TestRhythmDetector:
    """Tests for the RhythmDetector."""

    def test_initial_state_normal(self):
        from anti_anti_crawl.rhythm_detector import rhythm_detector
        # Reset state
        rhythm_detector._state = "normal"
        assert rhythm_detector.current_state == "normal"

    def test_delay_multiplier_normal(self):
        from anti_anti_crawl.rhythm_detector import rhythm_detector
        rhythm_detector._state = "normal"
        assert rhythm_detector.delay_multiplier == 1.0

    def test_delay_multiplier_suspicious(self):
        from anti_anti_crawl.rhythm_detector import rhythm_detector
        rhythm_detector._state = "suspicious"
        assert rhythm_detector.delay_multiplier == 2.0

    def test_delay_multiplier_captcha(self):
        from anti_anti_crawl.rhythm_detector import rhythm_detector
        rhythm_detector._state = "captcha"
        assert rhythm_detector.delay_multiplier == 3.0

    def test_record_response(self):
        from anti_anti_crawl.rhythm_detector import rhythm_detector
        rhythm_detector.record_response(3.0, 200)
        rhythm_detector.record_response(2.0, 200)
        avg = rhythm_detector.get_average_response_time()
        assert 2.0 <= avg <= 3.0

    def test_state_transitions_to_suspicious(self):
        from anti_anti_crawl.rhythm_detector import rhythm_detector
        rhythm_detector._state = "normal"
        # Record some slow responses
        for _ in range(5):
            rhythm_detector.record_response(12.0, 200)
        rhythm_detector._update_state()
        # Should become suspicious or captcha
        assert rhythm_detector._state in ("suspicious", "captcha")
