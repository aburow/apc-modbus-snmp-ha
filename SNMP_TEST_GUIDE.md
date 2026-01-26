# SNMP Fix Testing Guide

## Local Verification ✓

The SNMP helper has been fixed with the following changes:

### Code Changes
- ✓ UdpTransportTarget now uses **separate arguments**: `UdpTransportTarget(host, 161)`
- ✓ Timeout is enforced via `asyncio.wait_for()` wrapping the `get_cmd()` call
- ✓ Proper handling of `asyncio.TimeoutError` exceptions
- ✓ Enhanced debug logging for troubleshooting

### Syntax Verification
- ✓ Python syntax valid
- ✓ Correct API usage for pysnmp v3arch
- ✓ Proper timeout enforcement mechanism

## Manual Testing in Home Assistant

### Prerequisites
1. Home Assistant running with APC Modbus integration v0.3.1+ installed
2. Network access to SNMP-enabled devices:
   - Smart-UPS at 192.168.100.7
   - Smart-UPS at 192.168.100.8
   - Rack PDU at 192.168.100.117

### Test Steps

#### 1. Add a Device & Monitor Startup

**For Smart-UPS:**
```
Settings → Devices & Services → Create Integration
Search: APC UPS Modbus
- Host: 192.168.100.7
- SNMP Community: public
- Device Type: Smart-UPS
Create
```

**Expected Behavior:**
- Integration loads successfully
- Device info populated with:
  - Model (e.g., "Smart-UPS 1500")
  - Serial number
  - Firmware version
  - Device shows up in Home Assistant

#### 2. Check Home Assistant Logs

**Enable Debug Logging (optional):**
```yaml
logger:
  logs:
    custom_components.apc_modbus: debug
    custom_components.apc_modbus.snmp_helper: debug
```

**Look for successful SNMP queries:**
```
DEBUG (MainThread) [custom_components.apc_modbus.snmp_helper]
SNMP query to 192.168.100.7 OID 1.3.6.1.4.1.318.1.1.1.1.1.1.0 (timeout=5s)

DEBUG (MainThread) [custom_components.apc_modbus.snmp_helper]
SNMP query succeeded: 1.3.6.1.4.1.318.1.1.1.1.1.1.0=Smart-UPS 1500
```

**NOT Seeing (the error that was fixed):**
```
AbstractTransportTarget.__init__() got multiple values for argument 'timeout'
```

#### 3. Verify Device Information

After successful SNMP queries, check:

1. **Device Info Page:**
   - Settings → Devices & Services
   - Find "APC UPS" or device name
   - Click on device
   - Verify model, serial, firmware are populated

2. **Entity Details:**
   - Developer Tools → States
   - Look for `device_info` for the device
   - Should show manufacturer="APC" and model filled in

#### 4. Test Retry Logic

**To test retry logic without breaking things:**
1. Temporarily block SNMP port 161 on device with firewall
2. Watch logs for retry attempts: "attempt 1/3", "attempt 2/3", "attempt 3/3"
3. Then unblock SNMP and reload integration
4. Device info should populate on retry/reload

#### 5. Test Multiple Devices

Repeat the above for all test devices:
- ✓ Smart-UPS 1500 (192.168.100.7)
- ✓ Smart-UPS 3000 (192.168.100.8)
- ✓ Rack PDU (192.168.100.117)

### Success Criteria

✓ **All devices setup without errors**
✓ **Device info populated with model/serial/firmware**
✓ **No "AbstractTransportTarget" errors in logs**
✓ **All Modbus sensors updating normally**
✓ **SNMP queries showing as successful in debug logs**

### Troubleshooting

#### If SNMP still fails to retrieve metadata:

1. **Check firewall rules:**
   ```bash
   # From Home Assistant host
   nc -u -z -v 192.168.100.7 161
   ```

2. **Verify SNMP enabled on device:**
   - Check device web UI or management interface
   - Ensure SNMP community string is "public"

3. **Check Home Assistant logs for:**
   ```
   SNMP query to 192.168.100.7 OID ... (timeout=5s)
   SNMP query failed for 192.168.100.7 (OID ...): [error message]
   ```

4. **Verify retry logic is working:**
   - Look for "attempt 1/3", "attempt 2/3", "attempt 3/3" in logs
   - Integration should still load with empty device info if SNMP fails

#### If you see timeout errors:

```
asyncio.TimeoutError after 5s
```

This means SNMP took > 5 seconds to respond. Try:
- Check network latency: `ping -c 3 192.168.100.7`
- Check Home Assistant system performance
- Logs should still show "Warning: SNMP query timed out"

## Expected Log Output

### Successful Case:
```
DEBUG: Querying SNMP metadata (attempt 1/3)
DEBUG: Querying SNMP metadata from 192.168.100.7 (community: public)
DEBUG: SNMP query to 192.168.100.7 OID 1.3.6.1.4.1.318.1.1.1.1.1.1.0 (timeout=5s)
DEBUG: SNMP query succeeded: 1.3.6.1.4.1.318.1.1.1.1.1.1.0=Smart-UPS 1500
INFO: SNMP metadata retrieved: model=Smart-UPS 1500, serial=...
```

### Retry Case (some queries fail):
```
DEBUG: SNMP query failed: [error]
DEBUG: SNMP query to 192.168.100.7 OID ... (timeout=5s)
DEBUG: SNMP query succeeded: 1.3.6.1.4.1.318.1.1.1.1.2.3.0=ABC123456
INFO: SNMP metadata retrieved: model=Smart-UPS 1500, serial=ABC123456
```

### Fallback Case (SNMP completely unavailable):
```
WARNING: Failed to query SNMP metadata from 192.168.100.7 (attempt 1/3): [error]
WARNING: Failed to query SNMP metadata from 192.168.100.7 (attempt 2/3): [error]
WARNING: Failed to query SNMP metadata from 192.168.100.7 (attempt 3/3): [error]
WARNING: Unable to retrieve SNMP metadata after 3 attempts - proceeding without device info
```

Integration still loads and Modbus sensors work normally!

## Completion Checklist

- [ ] All devices can be added without SNMP errors
- [ ] Device info (model/serial) populated after ~5-10 seconds
- [ ] No "AbstractTransportTarget" errors in logs
- [ ] Modbus sensors loading and updating normally
- [ ] Multiple devices work independently
- [ ] Integration works even if SNMP fails initially
- [ ] Timeout handling works (asyncio.TimeoutError logged)

## Version Info

- **Fixed in:** v0.3.1
- **Commits:**
  - `ac2d6cb` - Pass host and port as separate arguments
  - `84ab878` - Use asyncio.wait_for for timeout enforcement
  - `de5883b` - Add retry logic and enhanced logging
