"""Tests for InverterPlugin ABC and PollResult dataclass."""
import pytest


class TestPollResult:
    """Verify PollResult dataclass fields and defaults."""

    def test_pollresult_has_common_registers(self):
        from venus_os_fronius_proxy.plugin import PollResult
        pr = PollResult(common_registers=[0] * 67, inverter_registers=[0] * 52, success=True)
        assert len(pr.common_registers) == 67

    def test_pollresult_has_inverter_registers(self):
        from venus_os_fronius_proxy.plugin import PollResult
        pr = PollResult(common_registers=[0] * 67, inverter_registers=[0] * 52, success=True)
        assert len(pr.inverter_registers) == 52

    def test_pollresult_success_field(self):
        from venus_os_fronius_proxy.plugin import PollResult
        pr = PollResult(common_registers=[], inverter_registers=[], success=True)
        assert pr.success is True

    def test_pollresult_error_default_none(self):
        from venus_os_fronius_proxy.plugin import PollResult
        pr = PollResult(common_registers=[], inverter_registers=[], success=True)
        assert pr.error is None

    def test_pollresult_error_can_be_set(self):
        from venus_os_fronius_proxy.plugin import PollResult
        pr = PollResult(common_registers=[], inverter_registers=[], success=False, error="timeout")
        assert pr.error == "timeout"


class TestInverterPluginABC:
    """Verify InverterPlugin ABC contract."""

    def test_cannot_instantiate_directly(self):
        from venus_os_fronius_proxy.plugin import InverterPlugin
        with pytest.raises(TypeError):
            InverterPlugin()

    def test_concrete_subclass_can_instantiate(self):
        from venus_os_fronius_proxy.plugin import InverterPlugin, PollResult

        class DummyPlugin(InverterPlugin):
            async def connect(self) -> None:
                pass

            async def poll(self) -> PollResult:
                return PollResult(common_registers=[], inverter_registers=[], success=True)

            def get_static_common_overrides(self) -> dict[int, int]:
                return {}

            def get_model_120_registers(self) -> list[int]:
                return []

            async def close(self) -> None:
                pass

        plugin = DummyPlugin()
        assert plugin is not None

    def test_has_connect_method(self):
        from venus_os_fronius_proxy.plugin import InverterPlugin
        assert hasattr(InverterPlugin, "connect")

    def test_has_poll_method(self):
        from venus_os_fronius_proxy.plugin import InverterPlugin
        assert hasattr(InverterPlugin, "poll")

    def test_has_get_static_common_overrides_method(self):
        from venus_os_fronius_proxy.plugin import InverterPlugin
        assert hasattr(InverterPlugin, "get_static_common_overrides")

    def test_has_get_model_120_registers_method(self):
        from venus_os_fronius_proxy.plugin import InverterPlugin
        assert hasattr(InverterPlugin, "get_model_120_registers")

    def test_has_close_method(self):
        from venus_os_fronius_proxy.plugin import InverterPlugin
        assert hasattr(InverterPlugin, "close")
