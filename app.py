from flask import Flask, render_template, request
import random
import io
import os
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError # Import HttpError for specific API errors
from googleapiclient.http import MediaIoBaseUpload
from google.oauth2 import service_account
# import csv # Not strictly needed for sheet upload

app = Flask(__name__)

# --- Google Drive API Setup ---
# *********************************************************************
# **Important:** Replace with your actual service account credentials file path!
# *********************************************************************
SERVICE_ACCOUNT_FILE = './xxx.json'  # <--- REPLACE THIS
# **Important:** Enter the email you want the file shared with below!
USER_EMAIL_TO_SHARE_WITH = "yyy@gmail.com" # <--- REPLACE THIS WITH YOUR EMAIL
# *********************************************************************
SCOPES = ['https://www.googleapis.com/auth/drive', 'https://www.googleapis.com/auth/spreadsheets']

creds = None
drive_service = None
sheets_service = None

try:
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    drive_service = build('drive', 'v3', credentials=creds)
    sheets_service = build('sheets', 'v4', credentials=creds)
    print("Google Drive and Sheets API services initialized successfully.")
except FileNotFoundError:
    print(f"ERROR: Service account key file not found at {SERVICE_ACCOUNT_FILE}")
    print("Please update the SERVICE_ACCOUNT_FILE variable in app.py")
except Exception as e:
    print(f"Error initializing Google Drive/Sheets API: {e}")


# --- Helper Function to Share File ---
def share_file_with_email(file_id, email_address, role='writer'):
    """Shares a file (by ID) with a specific email address using the Drive API."""
    if drive_service is None:
        print("Drive service not available for sharing.")
        return False
    try:
        permission_body = {
            'type': 'user',
            'role': role,
            'emailAddress': email_address
        }
        drive_service.permissions().create(
            fileId=file_id,
            body=permission_body,
            sendNotificationEmail=False  # Don't send email notification
        ).execute()
        print(f"Successfully shared file {file_id} with {email_address} as {role}.")
        return True
    except HttpError as error:
        print(f"An API error occurred while sharing file {file_id}: {error}")
        return False
    except Exception as e:
        print(f"An unexpected error occurred during sharing file {file_id}: {e}")
        return False

# --- Function to Upload as Sheet and Share ---
def upload_to_drive_as_sheet(filename, data, share_email=None):
    """Uploads data to Google Drive as a Google Sheet and optionally shares it."""
    if sheets_service is None:
        print("Google Sheets service not initialized. Cannot upload.")
        return None, False # Return ID and sharing status

    spreadsheet_id = None
    shared_successfully = False

    try:
        # 1. Create a new spreadsheet
        spreadsheet_body = {
            'properties': { 'title': filename }
        }
        spreadsheet = sheets_service.spreadsheets().create(
            body=spreadsheet_body,
            fields='spreadsheetId'
        ).execute()
        spreadsheet_id = spreadsheet.get('spreadsheetId')
        print(f"Created new spreadsheet with ID: {spreadsheet_id}")

        if not spreadsheet_id:
            print("Failed to create spreadsheet.")
            return None, False

        # 2. Prepare data for writing
        values_to_write = data # Expects list of lists: [['Header'], [card1], [card2]]
        write_body = { 'values': values_to_write }

        # 3. Write data to the sheet
        result = sheets_service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range="A1", # Start writing at cell A1
            valueInputOption="USER_ENTERED", # Interpret data as if user typed it
            body=write_body
        ).execute()
        print(f"{result.get('updatedCells')} cells updated in sheet {spreadsheet_id}.")

        # 4. Share the file if requested
        if share_email and spreadsheet_id:
            print(f"Attempting to share sheet {spreadsheet_id} with {share_email}...")
            shared_successfully = share_file_with_email(spreadsheet_id, share_email) # Call sharing function

        return spreadsheet_id, shared_successfully # Return both ID and sharing status

    except HttpError as error:
        print(f"An API error occurred during sheet upload/update: {error}")
        # Consider cleaning up if sheet was created but update/share failed
        # if spreadsheet_id: drive_service.files().delete(fileId=spreadsheet_id).execute() # Example cleanup
        return None, False
    except Exception as e:
        print(f"An unexpected error occurred during sheet upload: {e}")
        return None, False


# --- Luhn Algorithm Validation (Keep as before) ---
def luhn_algorithm(card_number):
    try:
        card_number = ''.join(filter(str.isdigit, card_number))
        card_number_list = [int(digit) for digit in card_number]
        n = len(card_number_list)
        sum_ = 0
        second_digit = False
        for i in range(n - 1, -1, -1):
            digit = card_number_list[i]
            if second_digit:
                digit *= 2
                if digit > 9: digit -= 9
            sum_ += digit
            second_digit = not second_digit
        return (sum_ % 10 == 0)
    except (ValueError, TypeError):
        return None

# --- Luhn Card Generation (Keep as before) ---
def generate_luhn_card(leading_digits, length=16):
    try:
        if not leading_digits.isdigit(): return None
        leading_len = len(leading_digits)
        if leading_len >= length: return None
        remaining_length = length - leading_len - 1
        if remaining_length < 0: return None
        base = leading_digits + ''.join(random.choices('0123456789', k=remaining_length))
        digits = [int(d) for d in base]
        n = len(digits)
        sum_ = 0
        second_digit = True
        for i in range(n - 1, -1, -1):
            digit = digits[i]
            if second_digit:
                digit *= 2
                if digit > 9: digit -= 9
            sum_ += digit
            second_digit = not second_digit
        check_digit = (10 - (sum_ % 10)) % 10
        return base + str(check_digit)
    except Exception as e:
        print(f"Error during card generation: {e}")
        return None

# --- Flask Route ---
@app.route('/', methods=['GET', 'POST'])
def index():
    card_number = None
    is_valid = None
    generated_cards = []
    leading_digits = None
    upload_message = None
    generated_cards_text = "" # For hidden field

    if request.method == 'POST':
        # Preserve data from previous step using hidden field if available
        # This helps keep generated cards visible if validation is done after generation
        if 'generated_cards_text_hidden' in request.form:
            generated_cards_text = request.form['generated_cards_text_hidden']
            generated_cards = generated_cards_text.splitlines() if generated_cards_text else []
        if 'leading_digits' in request.form: # Preserve leading digits too
             leading_digits = request.form['leading_digits']

        # --- Validation Logic ---
        if 'validate_card' in request.form:
            card_number = request.form['card_number']
            is_valid = luhn_algorithm(card_number)
            # We already preserved generated cards above if they existed

        # --- Generation Logic ---
        elif 'generate_cards' in request.form:
            leading_digits = request.form['leading_digits'] # Get from current form
            generated_cards = [] # Reset generated cards for this action
            try:
                card_length = int(request.form['card_length'])
                num_cards = int(request.form['num_cards'])

                if not (8 <= card_length <= 19): # Basic length check
                     generated_cards.append("Invalid card length (must be 8-19).")
                elif not 1 <= num_cards <= 10:
                    generated_cards.append("Number of cards must be between 1 and 10.")
                else:
                    for _ in range(num_cards):
                        card = generate_luhn_card(leading_digits, card_length)
                        if card is None:
                            generated_cards.append("Card generation failed (check inputs).")
                            break
                        else:
                            generated_cards.append(card)
                generated_cards_text = "\n".join(generated_cards) # Update text for hidden field

            except ValueError:
                generated_cards.append("Invalid input for length or number of cards.")
                generated_cards_text = "\n".join(generated_cards) # Update text

        # --- Upload Logic ---
        elif 'upload_cards' in request.form:
            generated_cards_text_from_form = request.form.get('generated_cards_text_hidden', '')
            # Ensure we use the cards passed from the form for upload
            if generated_cards_text_from_form:
                retrieved_cards = generated_cards_text_from_form.splitlines()
                # Update display variables as well
                generated_cards = retrieved_cards
                generated_cards_text = generated_cards_text_from_form

                filename = f"generated_cards_{random.randint(1000,9999)}.xlsx" # Add random element
                # Prepare data: Header row + data rows
                data_for_sheet = [["Generated Credit Card Numbers"]]
                data_for_sheet.extend([[card] for card in retrieved_cards if "failed" not in card.lower() and "invalid" not in card.lower()]) # Only upload valid-looking cards

                if len(data_for_sheet) > 1: # Check if there's actual data besides header
                     # Call the upload function, passing the target email
                    sheet_id, shared = upload_to_drive_as_sheet(
                        filename,
                        data_for_sheet,
                        share_email=USER_EMAIL_TO_SHARE_WITH # Use the constant defined at top
                    )

                    if sheet_id:
                        upload_message = f"Successfully uploaded as '{filename}' (ID: {sheet_id})."
                        if shared:
                            upload_message += f" Shared with {USER_EMAIL_TO_SHARE_WITH}."
                        else:
                             upload_message += f" Failed to share with {USER_EMAIL_TO_SHARE_WITH} (check console/permissions)."
                    else:
                        upload_message = "Upload to Google Drive failed. Check console for errors."
                else:
                     upload_message = "No valid card numbers were generated to upload."

            else:
                upload_message = "No generated card numbers found to upload."
            # Preserve validation input if it exists from a previous step
            if 'card_number' in request.form:
                 card_number = request.form['card_number']


    # Ensure text version is available for the template's hidden field
    if not generated_cards_text and generated_cards:
         generated_cards_text = "\n".join(generated_cards)

    return render_template('index.html',
                           card_number=card_number,
                           is_valid=is_valid,
                           generated_cards=generated_cards,
                           leading_digits=leading_digits,
                           upload_message=upload_message,
                           generated_cards_text_hidden=generated_cards_text) # Pass text for hidden field

if __name__ == '__main__':
    # Check if API services initialized before running
    if drive_service and sheets_service:
        app.run(debug=True)
    else:
        print("\nFlask app cannot start due to API initialization errors.")
        print("Please resolve the issues printed above (e.g., service account file path, API enabling) and restart.")
