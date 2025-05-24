import os
import json
from flask import Flask, request, jsonify, send_from_directory, abort, send_file
from flask_cors import CORS
from flask_mail import Mail, Message
from werkzeug.utils import secure_filename
from datetime import datetime, timezone
import logging
from logging.handlers import RotatingFileHandler

app = Flask(__name__)
CORS(app)

# Configure logging
logging.basicConfig(level=logging.INFO)
handler = RotatingFileHandler('email_server.log', maxBytes=10000, backupCount=3)
handler.setLevel(logging.INFO)
app.logger.addHandler(handler)

# Mail configuration
app.config.update(
    MAIL_SERVER='smtp.gmail.com',
    MAIL_PORT=587,
    MAIL_USE_TLS=True,
    MAIL_USERNAME='shashankab12@gmail.com',
    MAIL_PASSWORD='sijq utqf jqea yzcw',
    MAIL_DEFAULT_SENDER='shashankab12@gmail.com',
    UPLOAD_FOLDER=os.path.abspath('attachments'),
    MAX_CONTENT_LENGTH=16 * 1024 * 1024  # 16MB max upload size
)

mail = Mail(app)

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Constants
DATA_FILE = os.path.abspath('emails.json')
ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'gif', 'doc', 'docx', 'txt', 'csv', 'xlsx', 'pptx'}

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def load_emails():
    if not os.path.exists(DATA_FILE):
        return []
    try:
        with open(DATA_FILE, 'r') as f:
            data = json.load(f)
            if not isinstance(data, list):
                app.logger.error("Invalid data format in emails.json - expected list")
                return []
            return data
    except json.JSONDecodeError as e:
        app.logger.error(f"Error loading emails: {str(e)}")
        return []
    except Exception as e:
        app.logger.error(f"Unexpected error loading emails: {str(e)}")
        return []

def save_emails(emails):
    temp_file = DATA_FILE + '.tmp'
    try:
        with open(temp_file, 'w') as f:
            json.dump(emails, f, indent=4, default=str)
        
        if os.path.exists(temp_file):
            os.replace(temp_file, DATA_FILE)
    except Exception as e:
        app.logger.error(f"Error saving emails: {str(e)}")
        if os.path.exists(temp_file):
            os.remove(temp_file)
        raise

def generate_id():
    return datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f') + os.urandom(4).hex()

def save_attachment(file):
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        unique_name = f"{generate_id()}_{filename}"
        save_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_name)
        file.save(save_path)
        return unique_name
    return None

def cleanup_attachments(attachment_names):
    for attachment in attachment_names:
        try:
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], attachment)
            if os.path.exists(filepath):
                os.remove(filepath)
        except Exception as e:
            app.logger.warning(f"Could not delete attachment {attachment}: {str(e)}")

@app.route('/emails', methods=['GET'])
def get_emails():
    try:
        emails = load_emails()
        return jsonify(emails), 200
    except Exception as e:
        app.logger.error(f"Error in get_emails: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/emails', methods=['POST'])
def create_email():
    try:
        attachments = []
        email_data = {}
        
        if request.content_type and 'multipart/form-data' in request.content_type:
            email_data = {
                'from': request.form.get('from'),
                'to': request.form.get('to'),
                'subject': request.form.get('subject'),
                'body': request.form.get('body'),
                'folder': request.form.get('folder', 'inbox'),
                'starred': request.form.get('starred', 'false').lower() == 'true'
            }
            
            # Handle file attachments
            files = request.files.getlist('attachments')
            for file in files:
                if file and file.filename:
                    attachment_name = save_attachment(file)
                    if attachment_name:
                        attachments.append(attachment_name)
        else:
            if not request.is_json:
                return jsonify({'error': 'Content-Type must be application/json or multipart/form-data'}), 400
            email_data = request.get_json()
            attachments = email_data.get('attachments', [])
            
        required_fields = ['from', 'to', 'subject', 'body']
        missing_fields = [field for field in required_fields if not email_data.get(field)]
        if missing_fields:
            return jsonify({'error': f'Missing fields: {", ".join(missing_fields)}'}), 400

        emails = load_emails()
        email = {
            'id': generate_id(),
            'from': email_data['from'],
            'to': email_data['to'],
            'subject': email_data['subject'],
            'body': email_data['body'],
            'folder': email_data.get('folder', 'inbox'),
            'date': datetime.now(timezone.utc).isoformat(),
            'starred': email_data.get('starred', False),
            'attachments': attachments,
            'read': False
        }
        emails.append(email)
        save_emails(emails)
        return jsonify({'message': 'Email saved', 'email': email}), 201
    except Exception as e:
        app.logger.error(f"Error in create_email: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/emails/<email_id>', methods=['GET'])
def get_email(email_id):
    try:
        emails = load_emails()
        email = next((e for e in emails if e.get('id') == email_id), None)
        if not email:
            return jsonify({'error': 'Email not found'}), 404
        
        # Mark as read when fetched
        if not email.get('read', False):
            email['read'] = True
            save_emails(emails)
            
        return jsonify(email), 200
    except Exception as e:
        app.logger.error(f"Error in get_email: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/emails/<email_id>', methods=['PUT'])
def update_email(email_id):
    try:
        if not request.is_json:
            return jsonify({'error': 'Content-Type must be application/json'}), 400
            
        emails = load_emails()
        email_index = next((i for i, e in enumerate(emails) if e.get('id') == email_id), None)
        if email_index is None:
            return jsonify({'error': 'Email not found'}), 404
            
        data = request.get_json()
        allowed_fields = ['folder', 'starred', 'read']
        for field in allowed_fields:
            if field in data:
                emails[email_index][field] = data[field]
                
        save_emails(emails)
        return jsonify({'message': 'Email updated', 'email': emails[email_index]}), 200
    except Exception as e:
        app.logger.error(f"Error in update_email: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/emails/<email_id>', methods=['DELETE'])
def delete_email(email_id):
    try:
        emails = load_emails()
        email_to_delete = next((e for e in emails if e.get('id') == email_id), None)
        if not email_to_delete:
            return jsonify({'error': 'Email not found'}), 404
            
        # Clean up attachments
        if email_to_delete.get('attachments'):
            cleanup_attachments(email_to_delete['attachments'])
            
        emails = [e for e in emails if e.get('id') != email_id]
        save_emails(emails)
        return jsonify({'message': 'Email deleted'}), 200
    except Exception as e:
        app.logger.error(f"Error in delete_email: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/emails/delete-multiple', methods=['POST'])
def delete_multiple_emails():
    try:
        if not request.is_json:
            return jsonify({'error': 'Content-Type must be application/json'}), 400
            
        data = request.get_json()
        if 'ids' not in data or not isinstance(data['ids'], list):
            return jsonify({'error': 'Invalid request format'}), 400
            
        emails = load_emails()
        emails_to_delete = [e for e in emails if e.get('id') in data['ids']]
        
        # Clean up attachments from all deleted emails
        for email in emails_to_delete:
            if email.get('attachments'):
                cleanup_attachments(email['attachments'])
                
        emails = [e for e in emails if e.get('id') not in data['ids']]
        save_emails(emails)
        return jsonify({'message': f'{len(emails_to_delete)} emails deleted'}), 200
    except Exception as e:
        app.logger.error(f"Error in delete_multiple_emails: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/emails/<email_id>/star', methods=['PUT'])
def toggle_star(email_id):
    try:
        emails = load_emails()
        email_index = next((i for i, e in enumerate(emails) if e.get('id') == email_id), None)
        if email_index is None:
            return jsonify({'error': 'Email not found'}), 404
            
        emails[email_index]['starred'] = not emails[email_index].get('starred', False)
        save_emails(emails)
        return jsonify({
            'message': 'Star toggled', 
            'starred': emails[email_index]['starred'],
            'email_id': email_id
        }), 200
    except Exception as e:
        app.logger.error(f"Error in toggle_star: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/send-email', methods=['POST'])
def send_email():
    try:
        if 'multipart/form-data' not in request.content_type:
            return jsonify({'error': 'Content-Type must be multipart/form-data'}), 400

        to = request.form.get('to')
        subject = request.form.get('subject')
        body = request.form.get('body')
        
        if not to or not subject or not body:
            return jsonify({'error': 'Missing required fields (to, subject, or body)'}), 400

        # Save attachments first
        attachments = []
        files = request.files.getlist('attachments')
        for file in files:
            if file and file.filename:
                attachment_name = save_attachment(file)
                if attachment_name:
                    attachments.append(attachment_name)

        # Create email message
        msg = Message(
            subject=subject,
            recipients=[to],
            body=body,
            sender=app.config['MAIL_DEFAULT_SENDER']
        )
        
        # Attach files to the email
        for attachment in attachments:
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], attachment)
            with open(filepath, 'rb') as f:
                msg.attach(attachment, "application/octet-stream", f.read())

        # Send the email
        mail.send(msg)

        # Save to sent folder
        emails = load_emails()
        new_email = {
            'id': generate_id(),
            'from': app.config['MAIL_DEFAULT_SENDER'],
            'to': to,
            'subject': subject,
            'body': body,
            'folder': 'sent',
            'date': datetime.now(timezone.utc).isoformat(),
            'starred': False,
            'attachments': attachments,
            'read': True
        }
        emails.append(new_email)

        # If sending to self, also add to inbox
        if to == app.config['MAIL_DEFAULT_SENDER']:
            inbox_copy = new_email.copy()
            inbox_copy['id'] = generate_id()
            inbox_copy['folder'] = 'inbox'
            inbox_copy['read'] = False
            emails.append(inbox_copy)

        save_emails(emails)

        return jsonify({
            'message': 'Email sent successfully',
            'email': new_email
        }), 200

    except Exception as e:
        app.logger.error(f"Error in send_email: {str(e)}")
        return jsonify({'error': f'Failed to send email: {str(e)}'}), 500

@app.route('/attachments/<filename>', methods=['GET'])
def download_attachment(filename):
    try:
        # Security checks
        if not filename or '..' in filename or filename.startswith('/'):
            abort(400, description="Invalid filename")
        
        filename = secure_filename(filename)
        if not filename:
            abort(400, description="Invalid filename")
            
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        
        if not os.path.exists(filepath):
            app.logger.error(f"Attachment not found: {filepath}")
            abort(404, description="Attachment not found")
        
        # Determine the original filename
        original_filename = filename.split('_', 1)[-1] if '_' in filename else filename
        
        return send_file(
            filepath,
            as_attachment=True,
            download_name=original_filename,
            mimetype='application/octet-stream'
        )
    except Exception as e:
        app.logger.error(f"Error downloading attachment {filename}: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/attachments/<filename>/preview', methods=['GET'])
def preview_attachment(filename):
    try:
        if not filename or '..' in filename or filename.startswith('/'):
            abort(400, description="Invalid filename")
        
        filename = secure_filename(filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        
        if not os.path.exists(filepath):
            abort(404, description="Attachment not found")
        
        # Determine MIME type based on extension
        ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
        mime_types = {
            'pdf': 'application/pdf',
            'png': 'image/png',
            'jpg': 'image/jpeg',
            'jpeg': 'image/jpeg',
            'gif': 'image/gif',
            'txt': 'text/plain',
            'csv': 'text/csv',
            'doc': 'application/msword',
            'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation'
        }
        
        mimetype = mime_types.get(ext, 'application/octet-stream')
        
        return send_file(
            filepath,
            mimetype=mimetype,
            as_attachment=False
        )
    except Exception as e:
        app.logger.error(f"Error previewing attachment {filename}: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/emails/mark-read', methods=['POST'])
def mark_as_read():
    try:
        if not request.is_json:
            return jsonify({'error': 'Content-Type must be application/json'}), 400
            
        data = request.get_json()
        if 'ids' not in data or not isinstance(data['ids'], list):
            return jsonify({'error': 'Invalid request format'}), 400
            
        emails = load_emails()
        updated_count = 0
        
        for email in emails:
            if email.get('id') in data['ids'] and not email.get('read', False):
                email['read'] = True
                updated_count += 1
                
        if updated_count > 0:
            save_emails(emails)
            
        return jsonify({'message': f'{updated_count} emails marked as read'}), 200
    except Exception as e:
        app.logger.error(f"Error in mark_as_read: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/emails/move-to-folder', methods=['POST'])
def move_to_folder():
    try:
        if not request.is_json:
            return jsonify({'error': 'Content-Type must be application/json'}), 400
            
        data = request.get_json()
        if 'ids' not in data or not isinstance(data['ids'], list) or 'folder' not in data:
            return jsonify({'error': 'Invalid request format'}), 400
            
        valid_folders = ['inbox', 'sent', 'drafts', 'trash']
        if data['folder'] not in valid_folders:
            return jsonify({'error': f'Invalid folder. Must be one of: {", ".join(valid_folders)}'}), 400
            
        emails = load_emails()
        updated_count = 0
        
        for email in emails:
            if email.get('id') in data['ids'] and email.get('folder') != data['folder']:
                email['folder'] = data['folder']
                updated_count += 1
                
        if updated_count > 0:
            save_emails(emails)
            
        return jsonify({'message': f'{updated_count} emails moved to {data["folder"]}'}), 200
    except Exception as e:
        app.logger.error(f"Error in move_to_folder: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Not found'}), 404

@app.errorhandler(400)
def bad_request(error):
    return jsonify({'error': 'Bad request'}), 400

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    # Ensure data directories exist
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    
    # Initialize data file if it doesn't exist
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'w') as f:
            json.dump([], f)
    
    app.run(host='0.0.0.0', port=5000, debug=True)