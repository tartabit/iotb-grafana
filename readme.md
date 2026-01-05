# IOTB Grafana
This folder contains helper scripts to manage importing and exporing data from your Grafana instance.

## Grafana/Prometheus Deployment
You can use the `tartabit-monitoring` helm chart as a starting point, or deploy on your own.  If you need further instructions
they are available here: https://docs.tartabit.com/en/SelfHosting/MonitoringMetrics (login is required)

## Grafana Tools
Below you will find information on configuring the grafana tools scripts for importing and exporting dashboards and alerts.

### Installation
Installation instructions provided for linux, other platforms may vary.
```
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Grafana Export
Export all IoT Bridge dashboards to a folder.
```
python3 grafana-export.py http://<grafana-url>/api --token gls***b0fd8
```

### Grafana Import
Import all dashboards from a folder to your Grafana instance.
```
python3 grafana-import.py --url http://<grafana-url>/api --token gls***b0fd8 <folder>
```