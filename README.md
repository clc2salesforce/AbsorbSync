# AbsorbSync

Synchronize user data between fields in Absorb LMS. Syncs from a source field (default: `externalId`) to any destination field. You must specify either `--customField` or `--destinationField` to define the destination.

## Table of Contents

- [Features](#features)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
  - [Quick Start](#quick-start)
  - [Command Line Options](#command-line-options)
  - [Usage Examples](#usage-examples)
- [Filtering Options](#filtering-options)
- [Validation and Behavior](#validation-and-behavior)
- [Status Values](#status-values)
- [CSV Files](#csv-files)
- [Logging](#logging)
- [Performance and Fault Tolerance](#performance-and-fault-tolerance)
- [Security](#security)
- [Troubleshooting](#troubleshooting)

## Features

### Core Functionality
- Downloads values from any source field (default: `externalId`) in Absorb LMS user accounts
- Uploads values to any destination field (must be specified with `--customField` or `--destinationField`)
- Supports syncing from/to standard user fields (e.g., `externalId`, `username`, `emailAddress`) or custom fields (e.g., `customFields.string1`)
- Two ways to specify destination (one is required):
  - `--customField`: Shorthand for custom fields only (e.g., `decimal1` becomes `customFields.decimal1`)
  - `--destinationField`: Full field path for any destination (e.g., `externalId`, `customFields.string1`)
- Supports custom field types: `decimal*` (converted to float) and `string*` (kept as string)
- Also supports `date*` and `checkbox*` fields (treated as strings)
- Requires `--update` flag for actual changes (default is dry-run mode)
- Incremental CSV export for fault tolerance
- User confirmation before processing updates

### API Integration
- Absorb LMS REST API v2 authentication
- **Batch updates**: Uses POST `/users/upload/` endpoint to update up to 200 users per request
- **Parallel API requests** with configurable `--workers` for concurrent processing
- Exponential backoff retry logic for transient failures (429, 5xx errors)
- Pagination with page-based offsets

### Fault Tolerance and Resume
- **Crash-safe progress tracking** via append-only progress file
- **Automatic resume**: re-run with `--file` to continue from where a previous run stopped
- Failed rows (status: Failure) are automatically retried on resume
- Successfully processed rows (Success, Different, Wrong Format) are skipped on resume

### Filtering and Validation
- Filter by department ID
- Filter for blank custom field values only (e.g., blank `decimal1`)
- Numeric-only validation for source field values (`--alpha` flag required to enable alphanumeric)
- Skip or overwrite existing values

## Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/clc2salesforce/AbsorbSync.git
   cd AbsorbSync
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up your credentials:**
   ```bash
   cp secrets.txt.example secrets.txt
   # Edit secrets.txt with your Absorb LMS API credentials
   ```

## Configuration

Edit `secrets.txt` with your Absorb LMS API credentials:

```
ABSORB_API_URL=https://rest.sandbox.myabsorb.com
ABSORB_API_KEY=your-api-key-guid
ABSORB_API_USERNAME=your_username
ABSORB_API_PASSWORD=your_password
```

### Credentials Explained

- **ABSORB_API_URL**: Base URL for your Absorb LMS REST API (e.g., `https://rest.sandbox.myabsorb.com` or `https://rest.myabsorb.com`)
- **ABSORB_API_KEY**: API key GUID used for both the `x-api-key` header and `privateKey` in authentication
- **ABSORB_API_USERNAME**: Username for API authentication
- **ABSORB_API_PASSWORD**: Password for API authentication

**Important:** Never commit `secrets.txt` to version control. It's already excluded in `.gitignore`.

## Usage

### Quick Start

```bash
# Preview changes (dry-run mode - default)
python absorb_sync.py --customField decimal1

# Actually perform updates (requires --update flag)
python absorb_sync.py --customField decimal1 --update

# Get help
python absorb_sync.py --help
```

### Command Line Options

#### Configuration Options
- `--secrets FILE` - Path to secrets file (default: `secrets.txt`)
- `--log-file FILE` - Path to log file (default: `logs/absorb_sync_YYYYMMDD_HHMMSS.log`)
- `--csv-file FILE` - Path to CSV file for user data (default: `users_YYYYMMDD_HHMMSS.csv`)

#### Field Selection Options
- `--sourceField FIELD` - Source field to sync from (default: `externalId`). Can be any field from the user object (e.g., `externalId`, `username`, `emailAddress`) or a nested field like `customFields.string1`. For custom fields, specify the full path (e.g., `customFields.decimal1`).
- `--customField FIELD` - **Required** (unless `--destinationField` is used). Shorthand for syncing to a custom field. Specify only the field name without the `customFields` prefix (e.g., `decimal1`, `string1`). The script automatically prepends `customFields.` to the field name. Cannot be used with `--destinationField`.
- `--destinationField FIELD` - **Required** (unless `--customField` is used). Full path to any destination field (e.g., `externalId`, `username`, `customFields.string1`). Use this for non-custom fields or when you want full control over the field path. Cannot be used with `--customField`.

#### Processing Mode Options
- `--update` - Actually perform updates (default is dry-run mode)
- `--dry-run` - Explicitly enable dry-run mode (no changes made, this is the default)
- `--file FILE` - Process existing CSV file instead of downloading from API. Automatically resumes from where a previous run left off.
- `--workers N` - Number of parallel workers for concurrent API requests (default: 1). Tested with up to 50.

#### Filtering Options
- `--blank` - Filter to only users with null/empty destination field
- `--department DEPT_ID` - Filter by departmentId UUID

#### Validation and Behavior Options
- `--overwrite` - Update destination field even if it has a different value (default: skip and mark as "Different")
- `--alpha` - Allow alphanumeric source field values (default: numeric only, non-numeric marked as "Wrong Format")

#### Debug Options
- `--debug` - Enable debug mode (prints sensitive data including API keys - USE ONLY IN SANDBOX)

### Usage Examples

#### Basic Operations

```bash
# Dry-run to preview changes (default behavior)
python absorb_sync.py --customField decimal1

# Perform actual updates
python absorb_sync.py --customField decimal1 --update

# Use custom configuration files
python absorb_sync.py --customField decimal1 --secrets prod_secrets.txt --log-file logs/production.log --update

# Sync to a different custom field using --customField
python absorb_sync.py --customField string1 --update

# Sync to decimal2 instead of decimal1
python absorb_sync.py --customField decimal2 --update

# Sync from a different source field (e.g., username to string1)
python absorb_sync.py --sourceField username --customField string1 --update

# Sync from one custom field to another (e.g., string2 to decimal1)
python absorb_sync.py --sourceField customFields.string2 --customField decimal1 --update

# Sync to any field using --destinationField (e.g., username to externalId)
python absorb_sync.py --sourceField username --destinationField externalId --update

# Sync from a custom field to a standard field
python absorb_sync.py --sourceField customFields.string1 --destinationField username --update
```

#### Filtering Examples

```bash
# Only update users with blank custom field
python absorb_sync.py --customField decimal1 --blank --update

# Filter by specific department
python absorb_sync.py --customField decimal1 --department c458459d-2f86-4c66-a481-e17e6983f7ee --update

# Combine filters: blank custom field in specific department
python absorb_sync.py --customField decimal1 --blank --department c458459d-2f86-4c66-a481-e17e6983f7ee --update

```

#### Validation Examples

```bash
# Allow alphanumeric source values (default is numeric only)
python absorb_sync.py --customField decimal1 --alpha --update

# Overwrite existing decimal1 values even if different
python absorb_sync.py --customField decimal1 --overwrite --update

# Combine: allow alphanumeric and overwrite existing values
python absorb_sync.py --customField decimal1 --alpha --overwrite --update
```

#### Advanced Examples

```bash
# Process existing CSV file (skip download)
python absorb_sync.py --customField decimal1 --file users_20260219_123456.csv --update

# Use parallel workers for faster processing (10 concurrent API requests)
python absorb_sync.py --customField decimal1 --workers 10 --update

# Resume a previously interrupted run (progress is saved automatically)
python absorb_sync.py --customField decimal1 --file users_20260219_123456.csv --workers 10 --update

# Debug mode for troubleshooting (prints API keys in cleartext)
python absorb_sync.py --customField decimal1 --debug --dry-run

# Complete example: filter, validate, and update specific department
python absorb_sync.py \
  --customField decimal1 \
  --department c458459d-2f86-4c66-a481-e17e6983f7ee \
  --blank \
  --alpha \
  --overwrite \
  --update

# Sync email addresses to a custom string field
python absorb_sync.py \
  --sourceField emailAddress \
  --customField string3 \
  --alpha \
  --update

# Use --destinationField to sync to any field (not just customFields)
python absorb_sync.py \
  --sourceField customFields.decimal1 \
  --destinationField externalId \
  --update
```

## Filtering Options

### --blank Flag
Uses OData filter syntax to download only users where the destination field is null or empty.

**OData Filter:** 
- For custom fields: `_filter=customFields/{fieldName} eq null` (e.g., `customFields/decimal1 eq null`)
- For standard fields: `_filter={fieldName} eq null` (e.g., `externalId eq null`)

**Use Case:** Reduces download time for large user databases by only fetching users that need updating.

**Note:** The filter uses the destination field specified by `--customField` or `--destinationField`.

### --department Flag
Filters users by department ID UUID.

**OData Filter:** `_filter=departmentId eq guid'<department-id>'`

**Example:** `--department c458459d-2f86-4c66-a481-e17e6983f7ee`

**Combining Filters:** The script combines multiple filters using the `and` operator:
```
_filter=(customFields/{fieldName} eq null) and (departmentId eq guid'<department-id>')
```

**Example with custom field:**
```bash
python absorb_sync.py --customField string1 --blank --department c458459d-2f86-4c66-a481-e17e6983f7ee --update
```

## Validation and Behavior

### Source Field Format Validation

By default, the script validates that source field values are numeric only.

**Without --alpha flag:**
- Only numeric source field values are processed
- Non-numeric values are marked as "Wrong Format" and skipped

**With --alpha flag:**
- Alphanumeric source field values are allowed
- All non-blank source field values are processed

### Blank Source Field Handling

**Case 1: Blank source field, blank destination field**
- User is silently skipped (no action needed)

**Case 2: Blank source field, populated destination field**
- User is marked as "Different" and skipped
- Prevents accidentally clearing populated fields

### Overwrite Behavior

**Without --overwrite flag (default):**
- If source field value doesn't match the destination field value (after removing decimals for decimal fields), user is marked as "Different" and skipped
- Only updates users where the destination field is blank or matches the source field value

**With --overwrite flag:**
- All users are updated regardless of current destination field value
- Existing different values are replaced

**Comparison Logic:**
- For decimal fields: Decimals are removed before comparison (e.g., `8675309.00` → `8675309`)
- For string/date/checkbox fields: Direct string comparison is performed
- Source field value is compared as-is (numeric by default, alphanumeric with `--alpha`)

**Field Type Handling:**
- Decimal fields (`decimal1`, `decimal2`, etc.): Values are converted to float type
- String/date/checkbox fields: Values are kept as strings

## Status Values

The CSV file tracks processing status for each user:

| Status | Description |
|--------|-------------|
| **Retrieved** | User downloaded from API, not yet processed |
| **Success** | User successfully updated in Absorb LMS |
| **Failure** | Update failed (error logged) |
| **Different** | Skipped because source field value doesn't match the destination field (when --overwrite not used), OR source field is blank but the destination field is populated |
| **Wrong Format** | Source field value contains non-numeric characters (when --alpha not used) |

## CSV Files

### Automatic Generation

CSV files are automatically created with timestamped names:
```
users_20260219_123456.csv
```

### CSV Columns

- **Status** - Processing status (Retrieved, Success, Failure, Different, Wrong Format)
- **id** - User UUID
- **username** - Username
- **Source field column** - The column name matches the source field specified with `--sourceField`.
- **Destination field column** - The column name follows the pattern `current_{sanitized_field_path}` where dots are replaced with underscores.
- **user_data_json** - Complete user profile as JSON

### Incremental Updates

- CSV is written **incrementally after each batch** during download
- Status column is updated **after each user** during processing
- If the script fails, the CSV shows where it left off

### Reprocessing CSV Files

Use the `--file` flag to process an existing CSV file:

```bash
python absorb_sync.py --file users_20260219_123456.csv --update
```

This skips the download phase and processes users from the CSV file.

## Logging

### Log Files

- **Console** - Real-time progress bar
- **Log file** - Full logs

Default log file location: `logs/absorb_sync_YYYYMMDD_HHMMSS.log`

### Log Contents

- Authentication status
- Download progress (batch X of Y)
- User confirmation prompts
- Update progress
- Success/failure counts
- Error messages and stack traces

### Debug Mode

Enable with `--debug` flag:

```bash
python absorb_sync.py --debug --dry-run
```

**Debug output includes:**
- API URL
- API key (cleartext)
- Username (cleartext)
- Password (cleartext)
- HTTP request details (method, URL, headers, body)
- HTTP response details (status, headers, body)

⚠️ **WARNING:** Debug mode prints sensitive data in cleartext. Use only in sandbox environments.

## Performance and Fault Tolerance

### Parallel Processing

- Use `--workers N` to enable concurrent API requests (default: 1 for sequential)

### Thread-Safe Token Management

- Authentication token is generated **once** at startup
- Token is automatically refreshed if it expires during a long-running operation

### High Performance

- **Batch API calls**: Up to 200 users updated per request, tested with 50 concurrent requests
- Default page size: **500 users per batch** during download

### Fault Tolerance

**Progress Tracking:**
- Progress is written after each individual user completes
- If the script crashes, the progress file indicates where the process left off

**Resume Capability:**
- Use `--file` flag to resume from where a previous run stopped
- Rows with terminal statuses (Success, Different, Wrong Format) are skipped
- Rows that previously failed (Failure) are automatically retried
- Example: `python absorb_sync.py --customField decimal1 --file users_20260219_123456.csv --workers 10 --update`

**Exponential Backoff:**
- Automatic retry for transient failures
- Exponential backoff: 1s → 2s → 4s → 8s → 16s
- Maximum 5 retry attempts per request

### User Confirmation

Before processing updates, the script:
1. Downloads all users matching filters
2. Exports to CSV file
3. Displays total user count
4. Prompts: "Do you want to proceed with updating X users? (yes/y/no)"
5. Only proceeds if user confirms

## Security

### Credentials Management

- API credentials stored in separate `secrets.txt` file, update `secrets.txt.example` and rename

### Debug Mode

For any issues, enable debug mode to see detailed API communication:

```bash
python absorb_sync.py --debug --dry-run
```

This will show:
- Loaded configuration
- All HTTP requests (headers, body, URL)
- All HTTP responses (status, headers, body)

⚠️ **WARNING:** Debug mode prints sensitive data in cleartext. Use only in sandbox environments.
