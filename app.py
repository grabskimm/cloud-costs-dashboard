from flask import Flask, render_template, abort, request, jsonify
from flask_caching import Cache
import json
import requests
import pandas as pd
import os
from datetime import datetime, timedelta
import pytz
import time
import logging
from azure.identity import DefaultAzureCredential, ManagedIdentityCredential

app = Flask(__name__)
cache = Cache(app, config={'CACHE_TYPE': 'simple', 'CACHE_DEFAULT_TIMEOUT': 3600})
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

scope = os.environ['SCOPE']
reservation_cost = os.getenv('RESERVATION_COST', '0.00')
FETCH_CONSUMPTION_DATA = os.getenv('FETCH_MACC_DATA', 'false')

# Check if MANAGED_IDENTITY_CLIENT_ID is set and not empty
use_managed_identity = bool(os.getenv('MANAGED_IDENTITY_CLIENT_ID'))

if use_managed_identity:
    # Switch to Managed Identity
    managed_identity_client_id = os.environ['MANAGED_IDENTITY_CLIENT_ID']
    credential = ManagedIdentityCredential(client_id=managed_identity_client_id)
else:
    # Use default credentials
    credential = DefaultAzureCredential()

# Function to format UsageDate column if it exists
def format_usage_date_column(df):
    if 'UsageDate' in df.columns:
        # Convert UsageDate to datetime format
        df['UsageDate'] = pd.to_datetime(df['UsageDate'], format='%Y%m%d')

        # Convert UsageDate to the desired format (year-month-date)
        df['UsageDate'] = df['UsageDate'].dt.strftime('%B %d, %Y')
    return df

# Function to removed TagKey column if it exists
def removed_key_column(df):
    # Check if 'TagKey' is in the columns
    if 'TagKey' in df.columns:
        # Get columns containing 'TagKey'
        columns_to_drop = [col for col in df.columns if 'TagKey' in col]
        # Drop columns containing 'TagKey'
        df = df.drop(columns=columns_to_drop)   
    return df

# Function to replace column names containing a specific keyword
def replace_column_names_with_keyword(df, keyword, new_name):
    # Get a list of columns containing the keyword
    columns_to_replace = [col for col in df.columns if keyword in col]
    # Create a dictionary to map old column names to new ones
    rename_dict = {col: col.replace(keyword, new_name) for col in columns_to_replace}
    # Rename the columns
    df = df.rename(columns=rename_dict)
    return df

# Function to remove rows containing '-' followed by a number
def remove_rows_with_dash_and_number(df):
    # Define regex pattern to match '-' followed by a number
    pattern = r'-\d+'
    # Loop through each cell in the DataFrame and check if it matches the pattern
    mask = df.apply(lambda x: x.astype(str).str.contains(pattern, na=False)).any(axis=1)
    # Filter out rows where any cell matches the pattern
    return df[~mask]

def remove_rows_with_zero(df):
    # Iterate over columns and check if any column has $0.00
    rows_to_drop = df[df.apply(lambda row: any(val.strip() == '$0.00' for val in row.values if isinstance(val, str)), axis=1)].index
    # Drop rows with any column containing $0.00
    df_filtered = df.drop(index=rows_to_drop)
    return df_filtered

def remove_rows_with_empty_cells(df):
    # Iterate over rows and check if any row has an empty cell
    rows_to_drop = df[df.apply(lambda row: any(pd.isnull(val) or (isinstance(val, str) and val.strip() == '') for val in row.values), axis=1)].index
    return df.drop(rows_to_drop)

    # Function to replace column names containing keyword with new_name
def replace_column_names(df, keyword, new_name):
    columns_to_replace = [col for col in df.columns if keyword in col]
    rename_dict = {col: col.replace(keyword, new_name) for col in columns_to_replace}
    return df.rename(columns=rename_dict)

def fetch_consumption_data():
    url = f"https://management.azure.com/{scope}/providers/Microsoft.Consumption/lots?api-version=2021-05-01&$filter=source%20eq%20%27ConsumptionCommitment%27"

    token = credential.get_token('https://management.azure.com/.default')
    access_token = token.token

    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
        'x-ms-command-name': 'CostAnalysis',
        'ClientType': 'sxt-costs-app'
    }

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
        return data
    except requests.RequestException as e:
        print(f"Failed to fetch consumption data: {e}")
        return None

# Function to make JSON POST request and return DataFrame
def make_post_request(scope, payload, to=None):

    token = credential.get_token('https://management.azure.com/.default')
    access_token = token.token

    # Prepare URL
    url = f"https://management.azure.com/{scope}/providers/Microsoft.CostManagement/query?api-version=2023-11-01"
    
    # Prepare headers
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json',
        'x-ms-command-name': 'CostAnalysis',
        'ClientType': 'sxt-costs-app'
    }

    # Add 'to' parameter to payload if provided
    if to:
        payload['timeframe'] = {'to': to}

    # Make a request to the Azure Cost Management API
    response = requests.post(url, headers=headers, json=payload)
    response_json = response.json()

    # Process the response data and return as DataFrame
    if response.status_code == 200:
        # Extracting data from the response JSON
        columns = [col['name'] for col in response_json['properties']['columns']]
        rows = response_json['properties']['rows']

        # Convert to DataFrame
        df = pd.DataFrame(rows, columns=columns)

        # Remove Currency Column
        if 'Currency' in df.columns:
            df.drop(columns=['Currency'], inplace=True)

        # Move PreTaxCost Column to the end
        if 'PreTaxCost' in df.columns:
            df = df[[col for col in df.columns if col != 'PreTaxCost'] + ['PreTaxCost']]

        # Format Numbers
        for col in df.columns:
            if 'Cost' in col:
                df[col] = df[col].apply(lambda x: '${:,.2f}'.format(float(x)))

        # Remove rows containing '-' followed by a number
        df = format_usage_date_column(df)

         # Remove rows containing '-' followed by a number
        df = remove_rows_with_dash_and_number(df)

        # Remove TagKey column
        df = removed_key_column(df)

        # Replace TagValue with Resource Owner
        df = replace_column_names_with_keyword(df, 'TagValue', 'Owner:')

        # Replace UsageDate with Usage Date:
        df = replace_column_names_with_keyword(df, 'UsageDate', 'Usage Date:')

        df = replace_column_names_with_keyword(df, 'SubscriptionName', 'Subscription:')

        df = replace_column_names_with_keyword(df, 'ResourceGroup', 'Resource Group:')

        df = replace_column_names_with_keyword(df, 'ResourceType', 'Resource Type:')

        df = replace_column_names_with_keyword(df, 'MeterCategory', 'Category:')

        return df
    else:
        print(f"Error: Unable to retrieve data for Scope: {scope}")
        return None
    
# Function to make JSON POST request and return DataFrame
def make_post_request_api(scope, payload, to=None):
    try:
        token = credential.get_token('https://management.azure.com/.default')
        access_token = token.token

        # Prepare URL
        url = f"https://management.azure.com/{scope}/providers/Microsoft.CostManagement/query?api-version=2023-11-01"
    
        # Prepare headers
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json',
            'x-ms-command-name': 'CostAnalysis',
            'ClientType': 'sxt-costs-app'
        }

        # Add 'to' parameter to payload if provided
        if to:
            payload['timeframe'] = {'to': to}

        # Make a request to the Azure Cost Management API
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()  # This will raise an error for non-2xx responses
        
        # Process the response data and return as JSON
        if response.ok:
            return response.json(), None, response.status_code
        else:
            # Extract error message from response
            error_message = response.json().get('error', {}).get('message', 'Unknown error')
            return None, error_message, response.status_code
    except requests.RequestException as e:
        # Handle exceptions that occur during the API request
        return None, str(e), 500
    
    # Function to make JSON POST request and return DataFrame
def make_post_request_forecast_api(scope, payload, to_time_f, from_time_f):
    try:
        token = credential.get_token('https://management.azure.com/.default')
        access_token = token.token

        # Prepare URL
        forecast = f"https://management.azure.com/{scope}/providers/Microsoft.CostManagement/forecast?api-version=2023-11-01"
    
        # Prepare headers
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json',
            'x-ms-command-name': 'CostAnalysis',
            'ClientType': 'sxt-costs-app'
        }

        payload['timeframe'] = {'to': to_time_f}
        
        payload['timeframe'] = {'from': from_time_f}

        # Make a request to the Azure Cost Management API
        response = requests.post(forecast, headers=headers, json=payload)
        response.raise_for_status()  # This will raise an error for non-2xx responses
        
        # Process the response data and return as JSON
        if response.ok:
            return response.json(), None, response.status_code
        else:
            # Extract error message from response
            error_message = response.json().get('error', {}).get('message', 'Unknown error')
            return None, error_message, response.status_code
    except requests.RequestException as e:
        # Handle exceptions that occur during the API request
        return None, str(e), 500
    
# Function to categorize filenames based on prefixes
def categorize_filenames(filenames):
    categorized = {'daily': [], 'yesterday': [], 'mtd': [], 'ytd': [], 'last': []}
    for filename in filenames:
        if filename.startswith('daily'):
            categorized['daily'].append(filename)
        elif filename.startswith('yesterday'):
            categorized['yesterday'].append(filename)
        elif filename.startswith('mtd'):
            categorized['mtd'].append(filename)
        elif filename.startswith('last'):
            categorized['last'].append(filename)
        elif filename.startswith('ytd'):
            categorized['ytd'].append(filename)

    return categorized

@app.route('/')
@app.route('/index')
# @cache.cached()
def index():
    directory_path = 'body'  # Path to directory containing JSON files
    filenames = os.listdir(directory_path)
    categorized_filenames = categorize_filenames(filenames)
    return render_template('index.html', categorized_filenames=categorized_filenames, reservation_cost=reservation_cost)

@app.route('/<filename>')
@app.route('/<filename>.json')
# @cache.cached()
def display_result(filename):
    # Remove .json extension if present
    if filename.endswith('.json'):
        filename = filename[:-5]  # Remove last 5 characters (.json)

    directory_path = 'body'

    # Construct the JSON file path
    json_file = os.path.join(directory_path, filename + '.json')

    # Check if the JSON file exists
    if os.path.exists(json_file):
        # Load JSON data from the file
        with open(json_file, 'r') as f:
            json_data = json.load(f)

        # Adjust time parameter for files containing 'ytd'
        if 'ytd' in filename:
            to_time = datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ')
            json_data['timePeriod']['to'] = to_time

        # Get the current date and time
        current_time = datetime.now()

        # Calculate the start time for yesterday
        start_of_yesterday = (current_time - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        from_time = start_of_yesterday.strftime('%Y-%m-%dT%H:%M:%SZ')

        # Calculate the end time for yesterday
        end_of_yesterday = (current_time - timedelta(days=1)).replace(hour=23, minute=59, second=59, microsecond=999999)
        to_time = end_of_yesterday.strftime('%Y-%m-%dT%H:%M:%SZ')

        if 'yesterday' in filename:
            json_data['timePeriod']['from']= from_time
            json_data['timePeriod']['to'] = to_time

        # Make POST request using the adjusted scope, loaded JSON data, and time parameter
        df = make_post_request(scope, json_data)

        # Calculate total cost and total of all columns
        if df is not None:
            # Calculate sum of each column containing costs
            cost_columns = [col for col in df.columns if 'Cost' in col]
            for col in cost_columns:
                df[col] = df[col].replace('[$,]', '', regex=True).astype(float)
                # total_row = {col: '${:,.2f}'.format(df[col].sum()) for col in cost_columns}
    
            # Calculate total of all numeric columns
            numeric_columns = df.select_dtypes(include=['float64', 'int64']).columns
            for col in numeric_columns:
                # Convert to numeric, handling non-numeric values gracefully
                df[col] = pd.to_numeric(df[col], errors='coerce')

            # Apply formatting only to numeric values
            for col in numeric_columns:
                df[col] = df[col].apply(lambda x: '${:,.2f}'.format(x) if pd.notna(x) else '')

            # total_df = pd.DataFrame(total_row, index=['Total'])
            df = pd.concat([df])
            #total_df

            df = remove_rows_with_zero(df)
            df = remove_rows_with_empty_cells(df)

            # Convert df to HTML table
            html_table = df.to_html(classes='data', index=False)
            # Rename the column headers
            html_table = html_table.replace('<th>PreTaxCost</th>', '<th>Cost:</th>')
            
            # Get the current date and time
            desired_timezone = pytz.timezone('America/Los_Angeles')
            current_datetime = datetime.now(desired_timezone).strftime("%B %d, %Y %H:%M:%S")
            
            # Render the template with the HTML table and current date and time
            return render_template('result.html', filename=filename, html_table=html_table, last_update=current_datetime)
        else:
            return f"No data retrieved for {filename}"
    else:
        abort(404)

@app.route('/api/consumption')
@cache.cached()
def get_consumption_data():
    fetch_data = os.getenv('FETCH_CONSUMPTION_DATA', 'false').lower() == 'true'

    if not fetch_data:
        return jsonify({"message": "macc_status: fetch_data"}), 200

    retry_limit = 100

    for attempt in range(retry_limit):
        consumption_data = fetch_consumption_data()
        if consumption_data:
            return jsonify(consumption_data['value'])
        else:
            print(f"Attempt {attempt + 1} failed to fetch MACC Balance")
            if attempt < retry_limit - 1:
                time.sleep(70)
                
    return jsonify({"error": "Failed to fetch consumption data"}), 500

@app.route('/api/<filename>')
@app.route('/api/<filename>.json')
@cache.cached()
def display_result_api(filename):
    # Remove .json extension if present
    if filename.endswith('.json'):
        filename = filename[:-5]  # Remove last 5 characters (.json)

    directory_path = 'body'

    # Construct the JSON file path
    json_file = os.path.join(directory_path, filename + '.json')

    # Check if the JSON file exists
    if os.path.exists(json_file):
        # Load JSON data from the file
        with open(json_file, 'r') as f:
            json_data = json.load(f)

        # Adjust time parameter for files containing 'ytd'
        if 'ytd' in filename:
            to_time = datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ')
            json_data['timePeriod']['to'] = to_time

        # Get the current date and time
        current_time = datetime.now()

        # Calculate the start time for yesterday
        start_of_yesterday = (current_time - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        from_time = start_of_yesterday.strftime('%Y-%m-%dT%H:%M:%SZ')

        # Calculate the end time for yesterday
        end_of_yesterday = (current_time - timedelta(days=1)).replace(hour=23, minute=59, second=59, microsecond=999999)
        to_time = end_of_yesterday.strftime('%Y-%m-%dT%H:%M:%SZ')

        if 'yesterday' in filename:
            json_data['timePeriod']['from']= from_time
            json_data['timePeriod']['to'] = to_time
        
        # Calculate the start of the month
        start_of_month = current_time.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        from_time = start_of_month.strftime('%Y-%m-%dT%H:%M:%SZ')

        # Calculate the end of the month by finding the start of the next month, then subtracting a microsecond
        next_month = start_of_month.replace(month=start_of_month.month % 12 + 1)
        if start_of_month.month == 12:  # Handle December to January transition
            next_month = next_month.replace(year=start_of_month.year + 1)
        end_of_month = next_month - timedelta(microseconds=1)
        to_time = end_of_month.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'  # Truncate microseconds to 3 places

        if 'forecast' in filename:
            json_data['timePeriod']['from']= from_time
            json_data['timePeriod']['to'] = to_time

                
        retry_limit = 100

        for attempt in range(retry_limit):
            response, error, status_code = make_post_request_api(scope, json_data)
            if response:
                return jsonify(response)
            else:
                print(f"Attempt {attempt + 1} failed: {error}")
                if attempt < retry_limit - 1:
                    time.sleep(70)
    
        return jsonify({"error": error}), status_code if status_code else 500

@app.route('/api/forecast')
@app.route('/api/forecast.json')
@cache.cached()
def display_result_forecast_api():
    # Remove .json extension if present
    filename = 'forecast.json'
    if filename.endswith('.json'):
        filename = filename[:-5]  # Remove last 5 characters (.json)

    directory_path = 'body/forecast'

    # Construct the JSON file path
    json_file = os.path.join(directory_path + '.json')

    # Check if the JSON file exists
    if os.path.exists(json_file):
        # Load JSON data from the file
        with open(json_file, 'r') as f:
            json_data = json.load(f)

        # Get the current date and time
        current_time = datetime.now()
       
        # Calculate the start of the month
        start_of_month = current_time.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        from_time_f = start_of_month.strftime('%Y-%m-%dT%H:%M:%SZ')

        # Calculate the end of the month by finding the start of the next month, then subtracting a microsecond
        next_month = start_of_month.replace(month=start_of_month.month % 12 + 1)
        if start_of_month.month == 12:  # Handle December to January transition
            next_month = next_month.replace(year=start_of_month.year + 1)
        end_of_month = next_month - timedelta(microseconds=1)
        to_time_f = end_of_month.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'  # Truncate microseconds to 3 places

        json_data['timePeriod']['from']= from_time_f
        json_data['timePeriod']['to'] = to_time_f

                
        retry_limit = 100

        for attempt in range(retry_limit):
            response, error, status_code = make_post_request_forecast_api(scope, json_data, from_time_f, to_time_f)
            if response:
                return jsonify(response)
            else:
                print(f"Attempt {attempt + 1} failed: {error}")
                if attempt < retry_limit - 1:
                    time.sleep(70)
    
        return jsonify({"error": error}), status_code if status_code else 500
    
if __name__ == '__main__':
    app.run(debug=True)
