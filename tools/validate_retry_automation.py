import asyncio
import copy
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import yaml
from homeassistant.core import HomeAssistant, Context
from homeassistant.setup import async_setup_component
from homeassistant.helpers import frame, script
from homeassistant.components.automation.config import async_validate_config_item
from homeassistant.util import dt
from homeassistant import loader
from homeassistant.config_entries import ConfigEntries

STATUS = 'sensor.on_charger_3806_status'
HISTORY = 'sensor.on_charger_3806_last_session_state'
CABLE = 'binary_sensor.on_charger_3806_cable_connected'
READY = 'sensor.on_charger_3806_start_readiness'

async def scenario(raw, name, outcomes, expected_starts, stale=False, occupied=False):
    with TemporaryDirectory() as directory:
        hass = HomeAssistant(directory)
        loader.async_setup(hass)
        hass.config_entries = ConfigEntries(hass, {})
        hass.data['triggers'] = {}
        hass.data['trigger_platform_subscriptions'] = []
        hass.data['trigger_description_cache'] = {}
        hass.data['trigger_disabled_triggers'] = set()
        frame.async_setup(hass)
        await async_setup_component(hass, 'automation', {'automation': []})
        await hass.async_block_till_done()
        config = await async_validate_config_item(hass, 'automation', copy.deepcopy(raw))
        assert config is not None, 'Automation validation failed'
        actions = config['actions']
        seq = actions[0]['repeat']['sequence']
        for item in seq:
            if 'delay' in item:
                item['delay'] = timedelta(milliseconds=10)
            if 'wait_template' in item:
                item['timeout'] = timedelta(milliseconds=150)
        starts = []
        notifications = []
        def status(state='Available', active=False):
            hass.states.async_set(STATUS, state, {
                'monta_state': 'busy-charging' if active else 'available',
                'active_charge_present': active,
                'active_charge_id': 'active-session' if active else None,
                'last_successful_update': (dt.utcnow() - timedelta(seconds=200) if stale else dt.utcnow()).isoformat(),
            })
        hass.states.async_set(CABLE, 'on')
        hass.states.async_set(HISTORY, 'failed', {'charge_id':'old-session', 'failed_at':'2020-01-01T00:00:00Z', 'failure_code':'StartTransactionTimeout'})
        hass.states.async_set(READY, 'Ready to start')
        status('Charging' if occupied else 'Available', occupied)
        async def start(call):
            outcome = outcomes[len(starts)]
            starts.append(outcome)
            hass.states.async_set(READY, 'Ready to start', {
                'last_start_result': 'rejected' if outcome == 'rejected' else 'accepted',
                'last_start_attempt_at': dt.utcnow().isoformat(),
                'last_start_error': 'Payment denied' if outcome == 'rejected' else None,
            })
            if outcome == 'charging':
                status('Charging', True)
            elif outcome in ('timeout', 'payment'):
                status()
                hass.states.async_set(HISTORY, 'failed', {
                    'charge_id': f'failed-{len(starts)}', 'failed_at':dt.utcnow().isoformat(),
                    'failure_code':'StartTransactionTimeout' if outcome == 'timeout' else 'PaymentDenied',
                    'error_title': 'Start transaction timeout' if outcome == 'timeout' else 'Payment denied',
                })
            elif outcome == 'unplugged':
                hass.states.async_set(CABLE, 'off')
            else:
                status('Paused', True)
        async def notify(call):
            notifications.append(call.data)
            if call.data.get('title') == 'ON charging retry':
                async def refresh():
                    await asyncio.sleep(0.04)
                    if name == 'unplug-before-retry':
                        hass.states.async_set(CABLE, 'off')
                    elif name != 'outage-before-retry':
                        status()
                hass.async_create_task(refresh(), eager_start=False)
        hass.services.async_register('switch', 'turn_on', start)
        hass.services.async_register('notify', 'hakon', notify)
        hass.services.async_register('persistent_notification', 'create', notify)
        hass.services.async_register('persistent_notification', 'dismiss', lambda call: None)
        runner = script.Script(hass, actions, 'ON retry simulation', 'automation', script_mode='single')
        await runner.async_run(context=Context())
        assert len(starts) == expected_starts, (name, starts, notifications)
        print(name, 'PASS', len(starts), 'starts', [n.get('title') for n in notifications], flush=True)
        await hass.async_stop()
        await hass.async_block_till_done()

async def main():
    raw = yaml.safe_load((Path(__file__).resolve().parents[1] / 'examples/auto_start_with_retries.yaml').read_text())
    cases = [
        ('first-success',['charging'],1,False,False),
        ('timeout-retry-success',['timeout','charging'],2,False,False),
        ('three-timeouts',['timeout','timeout','timeout'],3,False,False),
        ('payment-no-retry',['payment'],1,False,False),
        ('rejected-no-retry',['rejected'],1,False,False),
        ('paused-no-retry',['paused'],1,False,False),
        ('unplugged',['unplugged'],1,False,False),
        ('unplug-before-retry',['timeout'],1,False,False),
        ('outage-before-retry',['timeout'],1,False,False),
        ('stale-no-start',[],0,True,False),
        ('occupied-no-start',[],0,False,True),
    ]
    for args in cases:
        await scenario(raw, *args)

asyncio.run(main())
