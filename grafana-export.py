import os
import requests
import json
import sys
import argparse
from datetime import datetime

# Default Grafana API information
DEFAULT_GRAFANA_URL = ''
DEFAULT_API_KEY = ''

# Parse command line arguments
parser = argparse.ArgumentParser(description='Export Grafana dashboards, alerts, and contact points.')
parser.add_argument('--url', help='Grafana API URL', default=os.environ.get('GRAFANA_URL', DEFAULT_GRAFANA_URL))
parser.add_argument('--token', help='Grafana API Token', default=os.environ.get('GRAFANA_TOKEN', DEFAULT_API_KEY))
args = parser.parse_args()

GRAFANA_URL = args.url
API_KEY = args.token

if not GRAFANA_URL or not API_KEY:
    print("Error: Grafana URL and API Key must be provided via environment variables (GRAFANA_URL, GRAFANA_TOKEN) or command line arguments (--url, --token).")
    sys.exit(1)

# Mask the API key for logging (show first 8 and last 8 characters)
masked_token = f"{API_KEY[:8]}{'*' * (len(API_KEY) - 16)}{API_KEY[-8:]}" if len(API_KEY) > 16 else "****"
print(f"Grafana URL: {GRAFANA_URL}")
print(f"Grafana Token: {masked_token}")

# Create a timestamped root folder
timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
EXPORT_ROOT = f'grafana-{timestamp}'

# Folder where dashboards will be saved
DOWNLOAD_FOLDER = os.path.join(EXPORT_ROOT, 'dashboards')
ALERTS_FOLDER = os.path.join(EXPORT_ROOT, 'alerts')
CONTACT_POINTS_FOLDER = os.path.join(EXPORT_ROOT, 'contact-points')
EXPORT_TAG = 'tartabit-iot-bridge'

# Create the folders if they don't exist
for folder in [DOWNLOAD_FOLDER, ALERTS_FOLDER, CONTACT_POINTS_FOLDER]:
    if not os.path.exists(folder):
        os.makedirs(folder)

# Set up headers for API requests
headers = {
    'Authorization': f'Bearer {API_KEY}',
    'Content-Type': 'application/json',
    'X-Disable-Redaction': 'true'
}

# Fetch all dashboards
dashboards_response = requests.get(f'{GRAFANA_URL}/search', headers=headers)
dashboards = dashboards_response.json()

# Download each dashboard
for dashboard in dashboards:
    dashboard_uid = dashboard['uid']
    dashboard_title = dashboard['title']
    dashboard_tags = dashboard['tags']

    # Fetch the dashboard configuration
    dashboard_response = requests.get(f'{GRAFANA_URL}/dashboards/uid/{dashboard_uid}', headers=headers)
    dashboard_data = dashboard_response.json()

    dashboard_slug = dashboard_title.lower().replace(' ', '').replace('/','-')

    if EXPORT_TAG in dashboard_tags:
        # Save the dashboard JSON to a file
        filename = os.path.join(DOWNLOAD_FOLDER, f'{dashboard_slug}.json')
        with open(filename, 'w') as file:
            json.dump(dashboard_data, file, indent=4)
        print(f'Downloaded dashboard: {dashboard_title} ({dashboard_uid})')

print('All dashboards downloaded successfully.')

# Fetch all alert rules
alert_rules_response = requests.get(f'{GRAFANA_URL}/v1/provisioning/alert-rules', headers=headers)
if alert_rules_response.status_code == 200:
    alert_rules = alert_rules_response.json()
    for rule in alert_rules:
        rule_title = rule['title']
        rule_uid = rule['uid']
        # Sanitize filename: replace spaces with underscores and remove non-alphanumeric except underscores and hyphens
        sanitized_title = "".join(c if c.isalnum() or c in (' ', '_', '-') else "" for c in rule_title).replace(' ', '_')
        # Save the alert rule JSON to a file
        filename = os.path.join(ALERTS_FOLDER, f'{sanitized_title}.json')
        with open(filename, 'w') as file:
            json.dump(rule, file, indent=4)
        print(f'Downloaded alert rule: {rule_title} ({rule_uid}) -> {filename}')
    print('All alert rules downloaded successfully.')
else:
    print(f'Failed to fetch alert rules: {alert_rules_response.status_code}')

# Fetch all contact points
contact_points_response = requests.get(f'{GRAFANA_URL}/v1/provisioning/contact-points', headers=headers)
if contact_points_response.status_code == 200:
    contact_points = contact_points_response.json()
    for cp in contact_points:
        cp_name = cp['name']
        cp_uid = cp.get('uid', cp_name) # Contact points might not have UID in older versions or specific setups, but provisioning API usually has it
        # Save the contact point JSON to a file
        filename = os.path.join(CONTACT_POINTS_FOLDER, f'{cp_name}.json')
        with open(filename, 'w') as file:
            json.dump(cp, file, indent=4)
        print(f'Downloaded contact point: {cp_name}')
    print('All contact points downloaded successfully.')
else:
    print(f'Failed to fetch contact points: {contact_points_response.status_code}')