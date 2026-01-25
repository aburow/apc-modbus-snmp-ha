# Quick Start: Testing Multi-Device-Type Support

## 5-Minute Quick Test

### 1. Verify Device Detection (2 min)

```bash
cd /home/dev/projects/apc-modbus-ha
python3 localonly/test_device_detection.py
```

Expected: All 8 tests passing ✓

### 2. Verify Rack PDU Capability Discovery (2 min)

```bash
python3 localonly/test_rack_pdu_capabilities.py
```

Expected: Successfully reads capability registers from 192.168.100.117

### 3. Check Code Syntax (1 min)

```bash
python3 -m py_compile custom_components/apc_modbus/{__init__,coordinator,sensor,binary_sensor,snmp_helper,device_types,register_factory,registers_smart_ups,registers_rack_pdu}.py 2>&1
echo "✓ All files compiled successfully" || echo "✗ Syntax errors found"
```

---

## 30-Minute Integration Test

### Home Assistant Setup

1. **Install Integration**
   ```
   HACS → Search "APC Modbus" → Install
   Restart Home Assistant
   ```

2. **Add Smart-UPS Device**
   ```
   Settings → Devices & Services → Create Automation
   Select "APC UPS Modbus Integration"
   Host: 192.168.100.7
   Port: 502 (default)
   SNMP Community: public
   Save
   ```

3. **Verify Smart-UPS**
   ```
   Check device is created:
   - Device name shows "Smart-UPS 1500" (or similar)
   - 39 sensors visible
   - 12 binary sensors visible
   - All entity IDs unchanged from before
   - All values updating (check history)
   ```

4. **Add Rack PDU Device**
   ```
   Settings → Devices & Services → Create Integration
   Select "APC UPS Modbus Integration"
   Host: 192.168.100.117
   Port: 502 (default)
   SNMP Community: public
   Save
   ```

5. **Verify Rack PDU**
   ```
   Check device is created:
   - Device name shows "NetShelter Rack PDU AP8XXX"
   - Device-level sensors visible (power, energy, state)
   - Phase sensors visible (L1, L2, L3)
   - Outlet sensors visible (count based on num_metered_outlets)
   - Bank sensors visible (count based on num_banks)
   - All values updating
   ```

---

## Debugging Quick Reference

### Check Device Type Detection

```bash
# View debug logs
tail -n 100 /path/to/home-assistant.log | grep "device_type\|Device type\|RACK_PDU\|SMART_UPS"
```

### Verify Coordinator Data

Home Assistant Developer Console:
```python
# Check coordinator state
hass.data['apc_modbus'][entry_id]['coordinator'].device_type
hass.data['apc_modbus'][entry_id]['coordinator'].device_capabilities
hass.data['apc_modbus'][entry_id]['coordinator'].data.keys()
```

### Test SNMP on Device

```bash
# Test SNMP connectivity
snmpget -v 2c -c public 192.168.100.117 1.3.6.1.4.1.318.1.1.1.1.1.1.0

# Test Modbus connectivity
python3 localonly/test_rack_pdu_capabilities.py
```

---

## Common Issues & Quick Fixes

| Issue | Check | Fix |
|-------|-------|-----|
| Device shows as SMART_UPS instead of RACK_PDU | SNMP port 161 open? | Check firewall, verify SNMP service running on device |
| Rack PDU: No outlet sensors created | Run `test_rack_pdu_capabilities.py` | Verify device is metered model, check capability register values |
| Missing sensors | Check Home Assistant logs | Verify coordinator update cycle succeeds, check device is accessible |
| SNMP timeout | Ping device | Check network, SNMP service status |
| High update cycle time | Check Modbus response | Verify device not overloaded, check network latency |

---

## Verification Checklist

### Smart-UPS Verification
- [ ] Device created with correct model name
- [ ] 39 sensors visible in entity list
- [ ] 12 binary sensors visible
- [ ] Battery charge % between 0-100
- [ ] Load current > 0 A
- [ ] Input voltage near mains (180-240V typical)
- [ ] Output voltage near nominal (120/208/240V)
- [ ] Status sensors show correct states

### Rack PDU Verification
- [ ] Device created with model "NetShelter Rack PDU AP8XXX"
- [ ] Device-level power reading > 0 kW (if loaded)
- [ ] Phase sensors created (L1, L2, L3 if 3-phase)
- [ ] Outlet sensors count matches num_metered_outlets capability
- [ ] Outlet currents show actual values if outlets loaded
- [ ] Bank sensors count matches num_banks capability
- [ ] All sensor units correct (A, W, kWh, V, etc.)

---

## File Structure Reference

```
custom_components/apc_modbus/
├── __init__.py                  # Entry point, device detection
├── coordinator.py               # Data polling coordinator
├── sensor.py                    # Sensor entity platform
├── binary_sensor.py             # Binary sensor platform
├── const.py                     # Constants
├── config_flow.py               # Configuration flow
├── snmp_helper.py               # SNMP utilities + detection
├── device_types.py              # Device type enum [NEW]
├── register_factory.py          # Register factory [NEW]
├── registers_smart_ups.py       # Smart-UPS registers [NEW - renamed]
└── registers_rack_pdu.py        # Rack PDU registers [NEW]

localonly/
├── test_device_detection.py     # Device detection tests [NEW]
└── test_rack_pdu_capabilities.py # Capability discovery test [NEW]
```

---

## Performance Baseline

### Expected Update Cycle Times

**Smart-UPS:**
- Block reads: 1-2 seconds
- Individual reads fallback: 3-5 seconds
- Typical: 2-3 seconds

**Rack PDU (24 outlets):**
- Block reads (capabilities only): 0.5 seconds
- Individual reads (all registers): 5-8 seconds
- Typical: 6-7 seconds (dynamic entity count)

### Memory Usage
- Per device: ~5-10 MB
- Overhead for dynamic entities: < 1 MB per 100 entities

---

## Next Steps

1. ✅ Run quick tests (5 min)
2. ✅ Manual integration test (30 min)
3. ✅ Verify backward compatibility
4. ✅ Test SNMP fallback (block SNMP port)
5. ✅ Monitor logs for 30 minutes
6. ✅ Check entity history updates
7. 📋 Create issue if problems found

---

## Contact & Support

For issues or questions:
1. Check `IMPLEMENTATION_NOTES.md` for architecture details
2. Check `VERIFICATION_CHECKLIST.md` for detailed testing steps
3. Review logs with debug enabled: `logger: logs: custom_components.apc_modbus: debug`
4. Open issue on GitHub with device model and error details
