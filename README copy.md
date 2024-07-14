# Cloud Cost Management Dashboard

## Overview

This lightweight application is designed to manage and display cloud costs. It includes features such as viewing costs by environment, team, owner, category, resource groups, subscriptions, and more. The application is built using Python and Flask for the backend and HTML/CSS/JavaScript for the frontend.

Currently, the dashboard only displays Azure Cloud Costs. Support for additional public clouds will be added based on demand.

## Features

- View Azure consumption commitment balance
- Display various costs, including reservations, forecasts, daily costs, month-to-date costs, and year-to-date costs
- Responsive design with various filters for data visualization

## Requirements

- Python 3.9
- Azure CLI
- Required environment variables:
  - `SCOPE`: The billing account ID (required)
  - `RESERVATION_COST`: The cost of existing reservations (optional)
  - `FETCH_MACC_DATA`: Set to false by default. Only set to true if you have a MACC Agreement (Optional)
  - `MANAGED_IDENTITY_CLIENT_ID`: The managed Identity Client ID (Required when running on Azure Web App)
- Minimum Azure permissions: `Billing Account Reader` permissions to the billing account

## Setup

### Step 1: Clone the Repository

```sh
git clone https://github.com/your-repo/azure-cloud-cost-management.git
cd azure-cloud-cost-management
```

### Step 2: Create and Activate a Virtual Environment
#### Unix-like (Linux, macOS)
```sh
python3 -m venv venv
source venv/bin/activate
```

### Step 3: Install Dependencies
With the virtual environment activated, install the required Python packages:
```sh
pip install -r requirements.txt
```

### Step 4: Login to Azure CLI
```sh
az login
```

### Step 4: Set Environment Variables
Set the required environment variables. This can be done directly in the terminal or by creating a `.env` file and loading it. For simplicity, we'll set them directly in the terminal.

#### Unix-like (Linux, macOS)
```sh
export SCOPE = "your_scope" # Your Billing account ID in the following format: providers/Microsoft.Billing/billingAccounts/BILLING_ACCOUNT_ID
export RESERVATION_COST = "12.34"  # Optional
export FETCH_MACC_DATA = true # Optional, set to false by default. Only set to true if you have a MACC Agreement 
```
For more information locating your account ID, refer to the [Azure documentation](https://learn.microsoft.com/en-us/azure/cost-management-billing/manage/view-all-accounts).

### Step 6: Run the Application
Start the Flask application:
```sh
python app.py
```
### Step 7: Access the Web Page
**UI Dashboard**: Open your web browser and go to `http://127.0.0.1:5000/`. The page should display the Azure Cloud cost management dashboard with the data injected from the environment variables.

**API Response**: Additionally, you can view the full raw API response by appending `api` to the hostname
before the web page path. For example: `http://127.0.0.1:5000/api/yesterday-grand-total`.

**Please note**: Due to strict rate limiting on the Cost Management API, responses may take up to 2 minutes (or more) to display depending on your billing account privileges.

## Full experince 
###  Tagging Setup
For the best functionality of the `environment`, `team`, and `owner` filters, the application expects you to have tagging set up on your Azure Resource Groups. The application specifically looks for the following TagKeys:

- `team`
- `owner`
- `environment`

### Setting Up Tags Using Azure CLI
If you do not have tagging set up yet, you can use Azure CLI or Azure Policy to assign tags based on your preferred values. Here is an example using Azure CLI:

1. **Install Azure CLI**: If you haven't already, install Azure CLI by following the instructions [here](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli).
2. **Login to Azure CLI**:
```sh
az login
```
3. **Assign Tags to a Resource Group**:
```sh
az group update --name <resource-group-name> --set tags.team="YourTeam" tags.owner="YourOwner" tags.environment="YourEnvironment"
```
Replace `<resource-group-name>`, `YourTeam`, `YourOwner`, and `YourEnvironment` with your actual resource group name and tag values.

4. **Verify Tags**:
```sh
az group show --name <resource-group-name> --query tags
```
This will assign the specified tags to your resource group, ensuring that the application can correctly filter and display data based on your tagging setup.

### Update Exsiting and Tag Key Value:
If your resource groups use different TagKeys, you can easily replace the expected `TagKey` value by running a replace command on `"name": "team"` with `"name": "YOUR_VALUE"`.

```sh
sed -i 's/"name": "team"/"name": "YOUR_VALUE"/g' body/*
```
This ensures that the application can correctly filter and display data based on your preferred tagging setup.

## Additional Deployment Methods
### Publish to an Azure Web App
1. **Create an Azure Web App**:
  - Configure Web App variables:
    - `APP_NAME="YOUR_APP_NAME"`
    - `RG_NAME="YOUR_RESOURCE_GROUP_NAME"`
    - `IDENTITY_NAME="$APP_NAME-identity"`
    - `SCOPE="providers/Microsoft.Billing/billingAccounts/<BILLING_ACCOUNT_ID>"`
    - `RESERVATION_COST=""` # Optional

```sh
az webapp up --sku F1 --name $APP_NAME --resource-group $RG_NAME --runtime "PYTHON|3.9"
```
  - Create the user-assigned managed identity
  ```sh
  az identity create --name $IDENTITY_NAME --resource-group $RG_NAME
  ```
  - Attach the managed identity to the Web App
  ```sh
  az webapp identity assign --name $IDENTITY_NAME --resource-group $RG_NAME --identities $APP_NAME
  ```
  - Get the client ID and principal ID of the managed identity
  ```sh
  CLIENT_ID=$(az identity show --name $IDENTITY_NAME --resource-group $RG_NAME --query clientId --output tsv)
  echo $CLIENT_ID
  ```
  - Assign Reader role to the managed identity on the billing account scope per steps [here](https://learn.microsoft.com/en-us/azure/cost-management-billing/manage/manage-billing-access)

2. **Configure Application Settings**:
```sh
az webapp config appsettings set --name $APP_NAME --resource-group $RG_NAME --settings SCOPE=$SCOPE MANAGED_IDENTITY_CLIENT_ID=$CLIENT_ID RESERVATION_COST=$RESERVATION_COST
```
3. **Deploy Your Application**:
Launch your Web App and configure via Deployment Center to deploy via GitHub Actions.

Alternatively, you can push the code directly via the web app SCM URL:
```sh
git remote add azure https://$APP_NAME.scm.azurewebsites.net:443/$APP_NAME.git
git push azure main
```
Ensure your application is secure by configuring a private endpoint and disabling public access. Additionally, you can easily set up Single Sign-On (SSO) with popular identity providers such as Microsoft, Google, and Apple directly from the Authentication tab in your Web App.

## Coming Soon: 
- Deploy to Kubernetes with Docker & Helm
- Terraform Module to deploy this application end-to-end
