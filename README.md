# GTM Implementation Explorer

A Streamlit MVP that reads the live Google Tag Manager implementation and explains the relationships between tags, triggers and variables.

## What it documents

- Every live Tag
- Every live Trigger
- Every live Variable
- Tag → Trigger relationships
- Trigger → Tag relationships
- Variable → Tag relationships
- Variable → Trigger relationships
- Variable → Variable dependencies
- Tag parameters/configuration
- Trigger conditions/configuration
- Variable configuration
- Workspace additions/changes/removals compared with live
- OpenAI assistant for questions and improvement recommendations

## Authentication

The app needs read-only access to the Google Tag Manager API.

### Recommended for a team deployment: service account

Create a Google Cloud service account, enable the Google Tag Manager API, grant the service account appropriate read access to the GTM account/container, and put its JSON fields in Streamlit secrets.

`.streamlit/secrets.toml`:

```toml
[gcp_service_account]
type = "service_account"
project_id = "YOUR_PROJECT"
private_key_id = "YOUR_PRIVATE_KEY_ID"
private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
client_email = "YOUR_SERVICE_ACCOUNT_EMAIL"
client_id = "YOUR_CLIENT_ID"
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "YOUR_CERT_URL"

OPENAI_API_KEY = "YOUR_OPENAI_API_KEY"
OPENAI_MODEL = "gpt-6-luna"
```

Do not commit this file.

### Local testing

Alternatively set a temporary Google OAuth access token:

```bash
GTM_ACCESS_TOKEN="your_token"
OPENAI_API_KEY="your_key"
```

## Run

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Important limitation

GTM configuration describes configured logic, not actual runtime behavior. The app can show that `{{DLV - form_name}}` is used, but it cannot know the actual runtime value on a page unless that value is present in the GTM configuration. Likewise, configured domain/path conditions are not a definitive list of URLs where a tag has actually fired.

The next version should add a Playwright runtime layer to visit URLs, capture dataLayer pushes and network requests, and reconcile runtime behavior with the GTM configuration.
