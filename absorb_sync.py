#!/usr/bin/env python3
"""
Absorb LMS External ID Sync Script

This script downloads the 'external ID' field from Absorb LMS user accounts
and uploads it back to the same users' 'Ext_ID' field.

Features:
- Exponential backoff retry logic
- Text file logging
- Dry run mode
- Secrets loaded from external file
"""

import argparse
import logging
import os
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional, Any

try:
    import requests
except ImportError:
    print("Error: 'requests' module not found. Install it with: pip install -r requirements.txt")
    sys.exit(1)


class AbsorbLMSClient:
    """Client for interacting with Absorb LMS API."""
    
    def __init__(self, api_url: str, api_key: str, username: str = None, password: str = None):
        """
        Initialize the Absorb LMS client.
        
        Args:
            api_url: Base URL for the Absorb LMS API
            api_key: API key for X-Absorb-API-Key header
            username: API username (optional, for OAuth)
            password: API password (optional, for OAuth)
        """
        self.api_url = api_url.rstrip('/')
        self.api_key = api_key
        self.username = username
        self.password = password
        self.session = requests.Session()
        # Set the API key header for all requests
        self.session.headers.update({
            "X-Absorb-API-Key": self.api_key
        })
        self.token = None
        self.use_oauth = bool(username and password)
        
    def authenticate(self) -> bool:
        """
        Authenticate with the Absorb LMS API.
        
        If username and password are provided, attempts OAuth authentication.
        Otherwise, relies on API key authentication only.
        
        Note: The X-Absorb-API-Key header must be set (done in __init__)
        
        Returns:
            bool: True if authentication successful, False otherwise
        """
        # If no username/password, rely on API key only
        if not self.use_oauth:
            logging.info("Using API key authentication only (no OAuth)")
            return True
        
        # Try OAuth authentication
        # Common Absorb LMS v2 OAuth endpoints: /oauth/token or /api/rest/v2/authentication/token
        # Try the standard OAuth endpoint first
        auth_endpoints = [
            f"{self.api_url}/oauth/token",
            f"{self.api_url}/authentication/token"
        ]
        
        headers = {
            "Content-Type": "application/x-www-form-urlencoded"
        }
        
        # OAuth password grant flow
        data = {
            "grant_type": "password",
            "username": self.username,
            "password": self.password
        }
        
        for auth_url in auth_endpoints:
            try:
                logging.info(f"Attempting OAuth authentication at: {auth_url}")
                response = self._retry_request(
                    method='POST',
                    url=auth_url,
                    headers=headers,
                    data=data
                )
                
                if response.status_code == 200:
                    result = response.json()
                    self.token = result.get('access_token')
                    if self.token:
                        self.session.headers.update({
                            "Authorization": f"Bearer {self.token}"
                        })
                        logging.info(f"OAuth authentication successful using {auth_url}")
                        return True
                    else:
                        logging.warning(f"No access_token in response from {auth_url}")
                elif response.status_code == 404:
                    logging.info(f"Endpoint {auth_url} not found, trying next...")
                    continue
                else:
                    logging.warning(f"Authentication failed at {auth_url}: {response.status_code} - {response.text}")
                    
            except Exception as e:
                logging.warning(f"Error trying {auth_url}: {str(e)}")
                continue
        
        # If all OAuth attempts failed, log warning but continue with API key only
        logging.warning("OAuth authentication failed, continuing with API key only")
        logging.warning("If API calls fail, verify your API key and credentials are correct")
        return True  # Don't fail completely, let API calls determine if auth is sufficient
    
    def _retry_request(self, method: str, url: str, max_retries: int = 5, 
                      initial_delay: float = 1.0, **kwargs) -> requests.Response:
        """
        Make an HTTP request with exponential backoff retry logic.
        
        Args:
            method: HTTP method (GET, POST, PUT, etc.)
            url: URL to request
            max_retries: Maximum number of retry attempts
            initial_delay: Initial delay in seconds before first retry
            **kwargs: Additional arguments to pass to requests
            
        Returns:
            requests.Response: The response object if successful
            
        Raises:
            Exception: If all retries are exhausted, an exception is always raised
                      rather than returning a response
        """
        delay = initial_delay
        last_error = None
        
        for attempt in range(max_retries):
            try:
                response = self.session.request(method, url, **kwargs)
                
                # If we get a rate limit or server error, retry
                if response.status_code in [429, 500, 502, 503, 504]:
                    if attempt < max_retries - 1:
                        logging.warning(
                            f"Retry {attempt + 1}/{max_retries} for {method} {url} "
                            f"(status: {response.status_code})"
                        )
                        time.sleep(delay)
                        delay *= 2  # Exponential backoff
                        continue
                    else:
                        # Last attempt failed with retryable status code
                        raise Exception(
                            f"Max retries exceeded. Last status: {response.status_code}"
                        )
                
                return response
                
            except requests.exceptions.RequestException as e:
                last_error = str(e)
                if attempt < max_retries - 1:
                    logging.warning(
                        f"Retry {attempt + 1}/{max_retries} for {method} {url} "
                        f"(error: {last_error})"
                    )
                    time.sleep(delay)
                    delay *= 2  # Exponential backoff
                else:
                    raise Exception(f"Max retries exceeded: {last_error}")
            
    def get_users(self, page_size: int = 100) -> List[Dict[str, Any]]:
        """
        Retrieve all users from Absorb LMS.
        
        Args:
            page_size: Number of users to retrieve per page
            
        Returns:
            List of user dictionaries
        """
        users = []
        page = 1
        
        while True:
            url = f"{self.api_url}/users"
            params = {
                "pageSize": page_size,
                "page": page
            }
            
            try:
                response = self._retry_request('GET', url, params=params)
                
                if response.status_code == 200:
                    data = response.json()
                    page_users = data.get('Users', [])
                    
                    if not page_users:
                        break
                        
                    users.extend(page_users)
                    logging.info(f"Retrieved page {page} with {len(page_users)} users")
                    
                    # Check if there are more pages
                    if len(page_users) < page_size:
                        break
                        
                    page += 1
                else:
                    logging.error(f"Failed to retrieve users: {response.status_code} - {response.text}")
                    break
                    
            except Exception as e:
                logging.error(f"Error retrieving users: {str(e)}")
                break
        
        return users
    
    def update_user_field(self, user_id: str, field_name: str, value: str) -> bool:
        """
        Update a custom field for a user.
        
        Args:
            user_id: User ID
            field_name: Name of the field to update
            value: Value to set
            
        Returns:
            bool: True if update successful, False otherwise
        """
        url = f"{self.api_url}/users/{user_id}"
        
        # Get current user data first
        try:
            response = self._retry_request('GET', url)
            if response.status_code != 200:
                logging.error(f"Failed to get user {user_id}: {response.status_code}")
                return False
                
            user_data = response.json()
            
            # Update the custom field
            if 'CustomFields' not in user_data:
                user_data['CustomFields'] = []
            
            # Find or create the field
            field_found = False
            for field in user_data['CustomFields']:
                if field.get('Name') == field_name:
                    field['Value'] = value
                    field_found = True
                    break
            
            if not field_found:
                user_data['CustomFields'].append({
                    'Name': field_name,
                    'Value': value
                })
            
            # Update the user
            headers = {
                "Content-Type": "application/json"
            }
            response = self._retry_request(
                'PUT',
                url,
                headers=headers,
                json=user_data
            )
            
            if response.status_code in [200, 204]:
                return True
            else:
                logging.error(
                    f"Failed to update user {user_id}: {response.status_code} - {response.text}"
                )
                return False
                
        except Exception as e:
            logging.error(f"Error updating user {user_id}: {str(e)}")
            return False


def load_secrets(secrets_file: str = 'secrets.txt') -> Dict[str, str]:
    """
    Load secrets from a text file.
    
    Args:
        secrets_file: Path to the secrets file
        
    Returns:
        Dictionary of configuration values
        
    Raises:
        FileNotFoundError: If secrets file doesn't exist
        ValueError: If required secrets are missing
    """
    if not os.path.exists(secrets_file):
        raise FileNotFoundError(
            f"Secrets file '{secrets_file}' not found. "
            f"Copy 'secrets.txt.example' to '{secrets_file}' and fill in your credentials."
        )
    
    secrets = {}
    with open(secrets_file, 'r') as f:
        for line in f:
            line = line.strip()
            # Skip comments and empty lines
            if not line or line.startswith('#'):
                continue
            
            if '=' in line:
                key, value = line.split('=', 1)
                secrets[key.strip()] = value.strip()
    
    # Validate required secrets
    required_keys = [
        'ABSORB_API_URL',
        'ABSORB_API_KEY'
    ]
    
    # Optional keys for OAuth (if not provided, API key only auth is used)
    optional_keys = [
        'ABSORB_API_USERNAME',
        'ABSORB_API_PASSWORD'
    ]
    
    missing_keys = [key for key in required_keys if key not in secrets]
    if missing_keys:
        raise ValueError(f"Missing required secrets: {', '.join(missing_keys)}")
    
    # Log if OAuth credentials are not provided
    missing_optional = [key for key in optional_keys if key not in secrets or not secrets[key]]
    if missing_optional:
        logging.info(f"Optional OAuth credentials not provided: {', '.join(missing_optional)}")
        logging.info("Will use API key authentication only")
    
    return secrets


def setup_logging(log_file: str = None) -> None:
    """
    Set up logging configuration.
    
    Args:
        log_file: Path to log file (optional)
    """
    log_format = '%(asctime)s - %(levelname)s - %(message)s'
    
    handlers = [logging.StreamHandler(sys.stdout)]
    
    if log_file:
        # Create logs directory if it doesn't exist
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir)
        handlers.append(logging.FileHandler(log_file))
    
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        handlers=handlers
    )


def sync_external_ids(client: AbsorbLMSClient, dry_run: bool = False) -> tuple:
    """
    Sync external IDs from 'external ID' field to 'Ext_ID' field.
    
    Args:
        client: Authenticated AbsorbLMSClient instance
        dry_run: If True, only simulate the sync without making changes
        
    Returns:
        Tuple of (success_count, error_count)
    """
    logging.info("Starting external ID sync...")
    
    if dry_run:
        logging.info("DRY RUN MODE - No changes will be made")
    
    # Get all users
    logging.info("Fetching users from Absorb LMS...")
    users = client.get_users()
    logging.info(f"Found {len(users)} users")
    
    success_count = 0
    error_count = 0
    skip_count = 0
    
    for user in users:
        user_id = user.get('Id')
        username = user.get('Username', 'Unknown')
        external_id = user.get('ExternalId')
        
        if not external_id:
            logging.debug(f"Skipping user {username} (ID: {user_id}) - no external ID")
            skip_count += 1
            continue
        
        logging.info(
            f"Processing user {username} (ID: {user_id}) - External ID: {external_id}"
        )
        
        if dry_run:
            logging.info(
                f"[DRY RUN] Would update Ext_ID field to: {external_id}"
            )
            success_count += 1
        else:
            if client.update_user_field(user_id, 'Ext_ID', external_id):
                logging.info(f"Successfully updated user {username}")
                success_count += 1
            else:
                logging.error(f"Failed to update user {username}")
                error_count += 1
    
    logging.info(f"\n{'='*60}")
    logging.info(f"Sync completed!")
    logging.info(f"Total users: {len(users)}")
    logging.info(f"Successful updates: {success_count}")
    logging.info(f"Errors: {error_count}")
    logging.info(f"Skipped (no external ID): {skip_count}")
    logging.info(f"{'='*60}\n")
    
    return success_count, error_count


def main():
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(
        description='Sync external IDs from External ID field to Ext_ID field in Absorb LMS'
    )
    parser.add_argument(
        '--secrets',
        default='secrets.txt',
        help='Path to secrets file (default: secrets.txt)'
    )
    parser.add_argument(
        '--log-file',
        default=None,
        help='Path to log file (default: logs/absorb_sync_YYYYMMDD_HHMMSS.log)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Run in dry-run mode (no changes will be made)'
    )
    
    args = parser.parse_args()
    
    # Generate default log file name at runtime if not specified
    if args.log_file is None:
        args.log_file = f'logs/absorb_sync_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'
    
    # Set up logging
    setup_logging(args.log_file)
    
    logging.info("="*60)
    logging.info("Absorb LMS External ID Sync")
    logging.info("="*60)
    
    try:
        # Load secrets
        logging.info(f"Loading secrets from {args.secrets}...")
        secrets = load_secrets(args.secrets)
        
        # Initialize client
        logging.info("Initializing Absorb LMS client...")
        client = AbsorbLMSClient(
            api_url=secrets['ABSORB_API_URL'],
            api_key=secrets['ABSORB_API_KEY'],
            username=secrets.get('ABSORB_API_USERNAME'),
            password=secrets.get('ABSORB_API_PASSWORD')
        )
        
        # Authenticate
        logging.info("Authenticating with Absorb LMS...")
        if not client.authenticate():
            logging.error("Authentication failed. Exiting.")
            sys.exit(1)
        
        # Sync external IDs
        success_count, error_count = sync_external_ids(client, dry_run=args.dry_run)
        
        # Exit with appropriate code
        if error_count > 0:
            logging.warning(f"Completed with {error_count} errors")
            sys.exit(1)
        else:
            logging.info("Completed successfully")
            sys.exit(0)
            
    except FileNotFoundError as e:
        logging.error(str(e))
        sys.exit(1)
    except ValueError as e:
        logging.error(str(e))
        sys.exit(1)
    except Exception as e:
        logging.error(f"Unexpected error: {str(e)}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
