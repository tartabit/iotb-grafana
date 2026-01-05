import os
import requests
import json
import sys
import argparse

# Default Grafana API information for the new instance
DEFAULT_GRAFANA_URL = ''
DEFAULT_API_KEY = ''

# Parse command line arguments
parser = argparse.ArgumentParser(description='Import Grafana dashboards, alerts, and contact points.')
parser.add_argument('folder', nargs='?', default='.', help='Folder to import from')
parser.add_argument('--url', help='Grafana API URL', default=os.environ.get('GRAFANA_URL', DEFAULT_GRAFANA_URL))
parser.add_argument('--token', help='Grafana API Token', default=os.environ.get('GRAFANA_TOKEN', DEFAULT_API_KEY))
args = parser.parse_args()

GRAFANA_URL = args.url
API_KEY = args.token
IMPORT_ROOT = args.folder

if not GRAFANA_URL or not API_KEY:
    print("Error: Grafana URL and API Key must be provided via environment variables (GRAFANA_URL, GRAFANA_TOKEN) or command line arguments (--url, --token).")
    sys.exit(1)

# Mask the API key for logging (show first 8 and last 8 characters)
masked_token = f"{API_KEY[:8]}{'*' * (len(API_KEY) - 16)}{API_KEY[-8:]}" if len(API_KEY) > 16 else "****"
print(f"Grafana URL: {GRAFANA_URL}")
print(f"Grafana Token: {masked_token}")

if not os.path.isdir(IMPORT_ROOT):
    print(f"Error: {IMPORT_ROOT} is not a directory.")
    sys.exit(1)

print(f"Importing from: {IMPORT_ROOT}")

# Folders containing the JSON files
DOWNLOAD_FOLDER = os.path.join(IMPORT_ROOT, 'dashboards')
ALERTS_FOLDER = os.path.join(IMPORT_ROOT, 'alerts')
CONTACT_POINTS_FOLDER = os.path.join(IMPORT_ROOT, 'contact-points')

# Set up headers for API requests to the new instance
headers = {
    'Authorization': f'Bearer {API_KEY}',
    'Content-Type': 'application/json'
}

print(f"{headers}")

importedFolders = {}

# Function to import a dashboard from a JSON file
def import_dashboard(filename):
    with open(filename, 'r') as file:
        dashboard_data = json.load(file)

    dashboard_data['dashboard']['id'] = None
    dashboard_data['overwrite'] = True
    dashboard_data['folderUid'] = dashboard_data['meta']['folderUid']

    folderUid = dashboard_data['meta']['folderUid']
    folderTitle = dashboard_data['meta']['folderTitle']

    dashboard_data['meta'] = None
    if not folderUid in importedFolders:
        new_folder = {'uid': folderUid, 'title': folderTitle, 'overwrite': True}
        response = requests.post(f'{GRAFANA_URL}/folders', headers=headers, json=new_folder)
        if response.status_code == 200:
            print(f'Imported folder: {new_folder["title"]}')
        else:
            print(f'Failed to import folder: {new_folder["title"]}, Status Code: {response.status_code}')
            print(response.text)
        importedFolders[folderUid] = True

    response = requests.post(f'{GRAFANA_URL}/dashboards/db', headers=headers, json=dashboard_data)
    if response.status_code == 200:
        print(f'Imported dashboard: {dashboard_data["dashboard"]["title"]}')
    else:
        print(f'Failed to import dashboard: {dashboard_data["dashboard"]["title"]}, Status Code: {response.status_code}')
        print(response.text)

# Function to import an alert rule from a JSON file
def import_alert_rule(filename):
    with open(filename, 'r') as file:
        rule_data = json.load(file)

    headers["X-Disable-Provenance"] = "true"

    rule_uid = rule_data['uid']
    # Check if the rule already exists
    response = requests.get(f'{GRAFANA_URL}/v1/provisioning/alert-rules/{rule_uid}', headers=headers)
    if response.status_code == 200:
        # Update existing rule
        response = requests.put(f'{GRAFANA_URL}/v1/provisioning/alert-rules/{rule_uid}', headers=headers, json=rule_data)
        if response.status_code == 200:
            print(f'Updated alert rule: {rule_data["title"]} ({rule_uid})')
        else:
            print(f'Failed to update alert rule: {rule_data["title"]}, Status Code: {response.status_code}')
            print(response.text)
    else:
        # Create new rule
        response = requests.post(f'{GRAFANA_URL}/v1/provisioning/alert-rules', headers=headers, json=rule_data)
        if response.status_code == 201:
            print(f'Imported alert rule: {rule_data["title"]} ({rule_uid})')
        else:
            print(f'Failed to import alert rule: {rule_data["title"]}, Status Code: {response.status_code}')
            print(response.text)

    headers.pop("X-Disable-Provenance")
# Function to import a contact point from a JSON file
def import_contact_point(filename):
    with open(filename, 'r') as file:
        cp_data = json.load(file)

    headers["X-Disable-Provenance"] = "true"

    cp_name = cp_data['name']
    cp_uid = cp_data.get('uid')

    if cp_uid:
        # Try to update if UID exists
        response = requests.put(f'{GRAFANA_URL}/v1/provisioning/contact-points/{cp_uid}', headers=headers, json=cp_data)
        if response.status_code == 202: # 202 Accepted is common for contact points
             print(f'Updated contact point: {cp_name}')
             return

    # If no UID or update failed (e.g. 404), try to create
    response = requests.post(f'{GRAFANA_URL}/v1/provisioning/contact-points', headers=headers, json=cp_data)
    if response.status_code == 202:
        print(f'Imported contact point: {cp_name}')
    else:
        print(f'Failed to import contact point: {cp_name}, Status Code: {response.status_code}')
        print(response.text)

    headers.pop("X-Disable-Provenance")

# Iterate over JSON files in the folder and import each dashboard
if os.path.exists(DOWNLOAD_FOLDER):
    for filename in os.listdir(DOWNLOAD_FOLDER):
        if filename.endswith('.json'):
            full_path = os.path.join(DOWNLOAD_FOLDER, filename)
            import_dashboard(full_path)
    print('All dashboards imported successfully.')

# Iterate over JSON files in the folder and import each alert rule
if os.path.exists(ALERTS_FOLDER):
    for filename in os.listdir(ALERTS_FOLDER):
        if filename.endswith('.json'):
            full_path = os.path.join(ALERTS_FOLDER, filename)
            import_alert_rule(full_path)
    print('All alert rules imported successfully.')

# Iterate over JSON files in the folder and import each contact point
if os.path.exists(CONTACT_POINTS_FOLDER):
    for filename in os.listdir(CONTACT_POINTS_FOLDER):
        if filename.endswith('.json'):
            full_path = os.path.join(CONTACT_POINTS_FOLDER, filename)
            import_contact_point(full_path)
    print('All contact points imported successfully.')