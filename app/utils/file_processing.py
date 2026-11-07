# app/utils/file_processing.py
import pandas as pd
import csv
import os
from flask import current_app
from app.extensions import db
from app.models import Participant, Draw
from datetime import datetime

def process_csv_file(file_path, draw_id):
    """Process CSV file and add participants to draw"""
    try:
        participants_added = 0
        duplicates = 0
        
        with open(file_path, 'r', encoding='utf-8') as file:
            # Try to detect delimiter
            sample = file.read(1024)
            file.seek(0)
            sniffer = csv.Sniffer()
            delimiter = sniffer.sniff(sample).delimiter
            
            # Read CSV
            df = pd.read_csv(file, delimiter=delimiter)
            
            # Assume first column contains phone numbers
            phone_column = df.columns[0]
            
            for _, row in df.iterrows():
                phone_number = str(row[phone_column]).strip()
                
                # Basic phone number validation
                if not is_valid_phone_number(phone_number):
                    continue
                
                # Check for duplicates in this draw
                existing = Participant.query.filter_by(
                    phone_number=phone_number, 
                    draw_id=draw_id
                ).first()
                
                if not existing:
                    participant = Participant(
                        phone_number=phone_number,
                        draw_id=draw_id,
                        source='csv_upload'
                    )
                    db.session.add(participant)
                    participants_added += 1
                else:
                    duplicates += 1
        
        db.session.commit()
        return True, f"Added {participants_added} participants, {duplicates} duplicates skipped"
        
    except Exception as e:
        current_app.logger.error(f"Error processing CSV: {e}")
        return False, f"Error processing file: {str(e)}"

def process_excel_file(file_path, draw_id):
    """Process Excel file and add participants to draw"""
    try:
        participants_added = 0
        duplicates = 0
        
        # Read Excel file
        df = pd.read_excel(file_path)
        
        # Assume first column contains phone numbers
        phone_column = df.columns[0]
        
        for _, row in df.iterrows():
            phone_number = str(row[phone_column]).strip()
            
            # Basic phone number validation
            if not is_valid_phone_number(phone_number):
                continue
            
            # Check for duplicates in this draw
            existing = Participant.query.filter_by(
                phone_number=phone_number, 
                draw_id=draw_id
            ).first()
            
            if not existing:
                participant = Participant(
                    phone_number=phone_number,
                    draw_id=draw_id,
                    source='excel_upload'
                )
                db.session.add(participant)
                participants_added += 1
            else:
                duplicates += 1
        
        db.session.commit()
        return True, f"Added {participants_added} participants, {duplicates} duplicates skipped"
        
    except Exception as e:
        current_app.logger.error(f"Error processing Excel: {e}")
        return False, f"Error processing file: {str(e)}"

def is_valid_phone_number(phone):
    """Basic phone number validation"""
    if not phone or len(phone) < 9:
        return False
    
    # Remove common separators and check if it's mostly digits
    clean_phone = ''.join(filter(str.isdigit, phone))
    return len(clean_phone) >= 9

def get_allowed_extensions():
    """Get allowed file extensions for upload"""
    return {'csv', 'xlsx', 'xls'}