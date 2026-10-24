Veriflow

Event: Hackoween – The Last Lantern (Climate/Disaster Tech)

Approach
Fixed thresholds, raise alarm.

Alert Classification
One alert, four possible causes:
- Sensor Fault
- Isolated Spike
- Missing Data
- Genuine Change

Target Audience
- Utility control-room operators
- Field sampling teams
- Campus water managers
- Municipal water managers

## Limit-aware detection

VeriFlow checks readings against absolute water-quality limits as well as its existing rolling anomaly detector. A guard band accounts for sensor error: near a limit, the system estimates the probability that the true reading has crossed it. For example, a pH reading of 7.4999 with a 7.5 upper limit and sensor error of 0.05 has about a 49.9% chance of being over the limit, so the alert does not need to wait for several consecutive flags.

Severity rises smoothly as a reading approaches and passes a limit. CUSUM compares readings with the beginning baseline to catch a sustained drift that a moving baseline might follow. Time-to-limit fits a recent trend and warns when it may reach a limit within the response window. The configured limits and sensor errors are placeholders and should be confirmed from sensor datasheets and water-quality standards.
