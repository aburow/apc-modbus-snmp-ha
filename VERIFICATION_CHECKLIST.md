# Multi-Device-Type Support Verification Checklist

## Pre-Testing Setup

### Required Test Environment
- [ ] Home Assistant test instance running latest version
- [ ] Network connectivity to test devices:
  - [ ] Smart-UPS at 192.168.100.7 or 192.168.100.8
  - [ ] Rack PDU at 192.168.100.117
- [ ] Devices accessible on SNMP port 161 (for model detection)
- [ ] Devices accessible on Modbus port 502

### Code Review
- [ ] All syntax checks passing: `python3 -m py_compile [files]`
- [ ] No import errors in coordinator.py
- [ ] Device type detection logic reviewed
- [ ] Register factory pattern reviewed
- [ ] Capability discovery logic reviewed

---

## Phase 1: Device Detection Testing

### SNMP Model String Detection

**Test:** Device type detection from various model strings

```bash
python3 localonly/test_device_detection.py
```

Expected output:
```
✓ Model: 'NetShelter Rack PDU AP8652'   => rack_pdu
✓ Model: 'AP8861'                       => rack_pdu
✓ Model: 'APDU4-XM'                     => rack_pdu
✓ Model: 'Smart-UPS 1500'               => smart_ups
✓ Model: 'SMART-UPS VT'                 => smart_ups
✓ Model: 'Smart UPS 3000'               => smart_ups
✓ Model: None                           => smart_ups
✓ Model: 'Unknown Device'               => smart_ups
```

- [ ] Device detection test passing
- [ ] All model patterns recognized correctly

### SNMP Integration

**Test 1: Smart-UPS SNMP Query**
```
Verify SNMP query works for Smart-UPS:
- Model string retrieved successfully
- Device type detected as SMART_UPS
- Metadata logged in debug output
```

- [ ] Smart-UPS SNMP query working
- [ ] Device type detected as SMART_UPS
- [ ] Metadata logged correctly

**Test 2: Rack PDU SNMP Query**
```
Verify SNMP query works for Rack PDU:
- Model string retrieved successfully
- Device type detected as RACK_PDU
- Metadata logged in debug output
```

- [ ] Rack PDU SNMP query working
- [ ] Device type detected as RACK_PDU
- [ ] Metadata logged correctly

---

## Phase 2: Rack PDU Functionality Testing

### Capability Discovery

**Test:** Read capability registers from Rack PDU

```bash
python3 localonly/test_rack_pdu_capabilities.py
```

Expected output:
```
Connecting to Rack PDU at 192.168.100.117:502...
Connected! Reading capability registers...
--------------------------------------------------
  num_phases           (0x009E): X
  num_metered_phases   (0x009F): X
  num_banks            (0x00A0): X
  num_outlets          (0x00A1): X
  num_metered_outlets  (0x00A2): X
--------------------------------------------------
Capability query complete
```

- [ ] Connection successful to Rack PDU
- [ ] All capability registers read successfully
- [ ] Values are reasonable (num_outlets <= 64, num_phases in [1, 3], etc.)

### Dynamic Entity Creation

**Test:** Verify correct number of entities created

Home Assistant Integration Test:
1. Add new device configuration for Rack PDU (192.168.100.117)
2. Check device registry:
   - [ ] Device type shows "NetShelter Rack PDU" (from SNMP model)
   - [ ] Serial number populated
   - [ ] Firmware version populated
3. Verify entities created:
   - [ ] Device-level sensors created (power, energy, state)
   - [ ] Phase sensors created (L1, L2, L3 based on num_phases)
     - [ ] Phase current (A)
     - [ ] Phase voltage (V)
     - [ ] Phase power (W)
     - [ ] Phase state
   - [ ] Outlet sensors created (based on num_metered_outlets)
     - [ ] Outlet current (A)
     - [ ] Outlet power (W)
     - [ ] Outlet energy (kWh)
     - [ ] Outlet alarm state
   - [ ] Bank sensors created (based on num_banks)
     - [ ] Bank current (A)
     - [ ] Bank state

### Data Updates

**Test:** Verify sensors receive data and update correctly

- [ ] All created sensors showing non-null values
- [ ] Sensor values updating on each coordinator cycle
- [ ] No errors in Home Assistant logs
- [ ] Update cycle time acceptable (< 30 seconds)

---

## Phase 3: Smart-UPS Backward Compatibility Testing

### Device Setup

**Test:** Add Smart-UPS device with existing setup

1. Add device configuration for Smart-UPS (192.168.100.7)
2. Verify device setup:
   - [ ] Connection successful to Smart-UPS
   - [ ] SNMP metadata retrieved
   - [ ] Device type detected as "Smart-UPS"

### Entity Verification

**Test:** Verify all Smart-UPS entities present with correct IDs

Expected entities (39 total):

**Battery Sensors (6):**
- [ ] Battery State of Charge (%)
- [ ] Battery Voltage (V)
- [ ] Runtime Remaining (min)
- [ ] UPS Internal Temperature (°C)
- [ ] Bad Battery Packs
- [ ] Total Battery Packs

**Load Sensors (2):**
- [ ] Load Current (A)
- [ ] Load Percent (%)

**Input Sensors (4):**
- [ ] Input Voltage (V)
- [ ] Input Frequency (Hz)
- [ ] Max Input Voltage (V)
- [ ] Min Input Voltage (V)

**Output Sensors (2):**
- [ ] Output Voltage (V)
- [ ] Nominal Output Voltage (V)

**Configuration Sensors (5):**
- [ ] Lower Transfer Point (V)
- [ ] Upper Transfer Point (V)
- [ ] Shutdown Delay (s)
- [ ] Low Battery Duration (min)
- [ ] Turn On Delay (s)

**Identification (1):**
- [ ] UPS ID

**Binary Sensors (12):**
- [ ] Low Battery Shutdown (Problem)
- [ ] Unable to Transfer - Overload (Problem)
- [ ] Main Relay Fault (Problem)
- [ ] Battery Charger Fault (Problem)
- [ ] Temperature Fault (Problem)
- [ ] Bypass Fault (Problem)
- [ ] Inverter Fault (Problem)
- [ ] UPS Online (Power)
- [ ] UPS On Battery (Power)
- [ ] UPS Overload (Problem)
- [ ] UPS Low Battery (Battery)
- [ ] UPS Replace Battery (Battery)

### Entity ID Consistency

**Test:** Verify entity IDs unchanged from previous version

For each sensor, verify:
- [ ] Entity ID follows pattern: `sensor.apc_ups_{sensor_name}`
- [ ] Entity ID unchanged from previous version
- [ ] Friendly name unchanged

Example: `sensor.apc_ups_battery_state_of_charge` should map to "Battery State of Charge"

### Data Quality

**Test:** Verify Smart-UPS sensors receive valid data

- [ ] All sensors showing non-null values
- [ ] Battery sensors showing reasonable values (charge %, voltage V, etc.)
- [ ] Load sensors showing reasonable values
- [ ] Input/output sensors showing reasonable values
- [ ] Status binary sensors reflecting actual device state

---

## Phase 4: Error Handling & Fallback Testing

### SNMP Unavailable Fallback

**Test:** Device setup when SNMP is unavailable

Setup:
1. Block port 161 (SNMP) from Home Assistant to devices
2. Add new device configuration
3. Verify fallback behavior:
   - [ ] Connection successful (Modbus port 502 working)
   - [ ] Device type defaults to SMART_UPS
   - [ ] Warning logged about SNMP failure
   - [ ] Modbus polling continues successfully
   - [ ] All sensors created and updating

### Invalid/Missing Register Handling

**Test:** Device handles missing or invalid register data

During normal operation:
- [ ] No crashes when register read fails
- [ ] Failed registers logged at DEBUG level
- [ ] Other sensors continue updating
- [ ] Device remains responsive

### Network Interruption Recovery

**Test:** Device recovers from network interruptions

During normal polling:
1. Temporarily disconnect device network
2. Observe:
   - [ ] Connection error logged
   - [ ] Coordinator attempts reconnect
   - [ ] After reconnect, polling resumes
   - [ ] No entity state corruption

---

## Phase 5: Performance Testing

### Update Cycle Time

**Test:** Measure coordinator update cycle performance

Monitor Home Assistant logs:
- [ ] Smart-UPS update cycle time: < 5 seconds (expected: 2-3s)
- [ ] Rack PDU update cycle time: < 10 seconds (expected: 5-8s with dynamic entities)
- [ ] No timeout errors (default: 2 min timeout)

### Entity Count & Performance

- [ ] Smart-UPS: 39 sensors + 12 binary sensors = 51 entities
  - [ ] Dashboard loads quickly with all entities
  - [ ] No UI lag when viewing device page
- [ ] Rack PDU: X sensors dynamically based on capabilities
  - [ ] Scales well with entity count
  - [ ] Dashboard performance acceptable

### Memory Usage

Monitor Home Assistant memory during:
- [ ] Device discovery
- [ ] Initial refresh cycle
- [ ] Extended operation (1+ hour)

- [ ] No memory leaks detected
- [ ] Memory usage stable over time

---

## Phase 6: Integration Testing

### Full Setup Scenario

**Test:** Complete setup with both device types

1. Home Assistant instance running
2. Add Smart-UPS device (192.168.100.7)
3. Wait for first refresh cycle
4. Verify Smart-UPS working correctly
5. Add Rack PDU device (192.168.100.117)
6. Wait for first refresh cycle
7. Verify Rack PDU working correctly
8. Both devices operating independently:
   - [ ] Smart-UPS sensors updating
   - [ ] Rack PDU sensors updating
   - [ ] No interference between devices
   - [ ] Device views show correct information

### Reload Behavior

**Test:** Integration reload/restart behavior

1. Configuration valid, no errors during load
2. Reload integration (Developer Tools → YAML → Reload Automations, Scripts & Scenes)
3. Verify after reload:
   - [ ] Both devices reconnect successfully
   - [ ] Entity states preserved
   - [ ] No orphaned entities

### Unload/Reload Devices

**Test:** Individual device unload/reload

1. Remove Smart-UPS device from config
2. Verify:
   - [ ] Smart-UPS entities removed
   - [ ] Rack PDU devices unaffected
3. Add Smart-UPS back
4. Verify:
   - [ ] Smart-UPS entities recreated
   - [ ] Entity states correct

---

## Documentation Review

- [ ] README.md updated with multi-device support info
- [ ] Supported devices section lists:
  - [ ] Smart-UPS with model examples
  - [ ] NetShelter Rack PDU with model examples
- [ ] Configuration examples show both device types
- [ ] INSTALLATION_NOTES.md created or updated
- [ ] Known limitations documented

---

## Final Sign-Off

- [ ] All phases tested and verified
- [ ] No blocking issues identified
- [ ] Performance acceptable
- [ ] Code review completed
- [ ] Documentation complete
- [ ] Ready for release

**Tested by:** ___________________
**Date:** ___________________
**Version:** ___________________

## Post-Release Monitoring

After release, monitor for:
- [ ] Issue reports about device detection
- [ ] Issues with existing Smart-UPS installations
- [ ] Issues with new Rack PDU support
- [ ] Performance regressions
- [ ] Unexpected SNMP timeouts

---

## Appendix A: Common Issues & Troubleshooting

### Issue: Device Type Detected as SMART_UPS Instead of RACK_PDU

**Cause:** SNMP query failed or model string doesn't match pattern
**Solution:** Check SNMP accessibility, verify device model name contains "AP8", "APDU", or "Rack PDU"

### Issue: Rack PDU Capability Discovery Fails

**Cause:** Device doesn't respond to capability register reads
**Solution:** Verify device is Rack PDU, check Modbus accessibility, verify register addresses

### Issue: Smart-UPS Entities Missing or Different IDs

**Cause:** Register loading issue or entity ID changes
**Solution:** Check coordinator logs for device type, verify `registers_smart_ups.py` intact

### Issue: High Update Cycle Time

**Cause:** Too many registers being read, network latency, device overload
**Solution:** Check network connectivity, verify device is responsive, check Home Assistant CPU usage

### Issue: SNMP Timeout on Every Query

**Cause:** SNMP service not running on device, firewall blocking, network issue
**Solution:** Verify SNMP enabled on device, check firewall rules, ping device to verify connectivity
