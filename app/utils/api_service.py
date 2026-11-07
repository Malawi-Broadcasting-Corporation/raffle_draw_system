# app/utils/api_service.py
import requests
import time
import json
from threading import Thread, Event
from flask import current_app
from app.extensions import db
from app.models import APIConfig, Participant, Draw, APIResponseLog
from datetime import datetime

class APIService:
    def __init__(self):
        self.is_running = False
        self.polling_thread = None
        self.polling_event = Event()
        self._app = None
    
    @property
    def app(self):
        if self._app is None:
            from app import create_app
            self._app = create_app()
        return self._app
    
    def start_polling(self):
        """Start polling the external API"""
        if self.is_running:
            return False
        
        self.is_running = True
        self.polling_event.clear()
        self.polling_thread = Thread(target=self._polling_worker)
        self.polling_thread.daemon = True
        self.polling_thread.start()
        return True
    
    def stop_polling(self):
        """Stop polling the external API"""
        self.is_running = False
        self.polling_event.set()
        if self.polling_thread:
            self.polling_thread.join(timeout=5)
    
    def _polling_worker(self):
        """Background worker that polls the API"""
        with self.app.app_context():
            while self.is_running and not self.polling_event.is_set():
                try:
                    self._fetch_from_api()
                    
                    # Wait for the configured interval
                    api_config = APIConfig.query.first()
                    if api_config:
                        self.polling_event.wait(api_config.refresh_interval * 60)
                    else:
                        self.polling_event.wait(300)
                        
                except Exception as e:
                    print(f"API polling error: {e}")
                    self.polling_event.wait(300)
    
    def _fetch_from_api(self):
        """Fetch data from the external API"""
        api_config = APIConfig.query.first()
        if not api_config or not api_config.is_active or not api_config.endpoint_url:
            return
        
        # Log the API request
        response_log = APIResponseLog(
            api_config_id=api_config.id,
            request_url=api_config.endpoint_url,
            request_method='GET',
            timestamp=datetime.utcnow()
        )
        
        try:
            headers = {}
            
            # Setup authentication
            if api_config.auth_method == 'api_key' and api_config.api_key:
                headers['Authorization'] = f'Bearer {api_config.api_key}'
            elif api_config.auth_method == 'basic_auth' and api_config.api_key:
                headers['Authorization'] = f'Basic {api_config.api_key}'
            
            print(f"Fetching from API: {api_config.endpoint_url}")
            
            # Make API request
            response = requests.get(
                api_config.endpoint_url,
                headers=headers,
                timeout=30
            )
            
            print(f"API Response Status: {response.status_code}")
            
            # Log response details
            response_log.response_status = response.status_code
            response_log.response_headers = json.dumps(dict(response.headers))
            
            if response.status_code == 200:
                data = response.json()
                response_log.response_body = json.dumps(data)
                print(f"API Response Data: {data}")
                
                # Process successful response
                added_count = self._process_api_response(data)
                response_log.participants_added = added_count
                response_log.success = True
               
                api_config.last_sync = datetime.utcnow()
                db.session.add(response_log)
                db.session.commit()
                print("Successfully fetched data from API")
                
            else:
                # Log error response
                try:
                    error_data = response.json()
                    response_log.response_body = json.dumps(error_data)
                    response_log.error_message = f"HTTP {response.status_code}: {error_data}"
                except:
                    response_log.response_body = response.text
                    response_log.error_message = f"HTTP {response.status_code}"
                
                response_log.success = False
                db.session.add(response_log)
                db.session.commit()
                print(f"API returned status code: {response.status_code}")
                
        except requests.exceptions.RequestException as e:
            error_msg = f"API request failed: {e}"
            print(error_msg)
            response_log.error_message = error_msg
            response_log.success = False
            db.session.add(response_log)
            db.session.commit()
        except Exception as e:
            error_msg = f"Error processing API response: {e}"
            print(error_msg)
            response_log.error_message = error_msg
            response_log.success = False
            db.session.add(response_log)
            db.session.commit()
    
    def _process_api_response(self, data):
        """Process the API response with flexible format handling"""
        try:
            api_config = APIConfig.query.first()
            if not api_config:
                return 0
            
            # Get the default draw ID from configuration
            default_draw_id = api_config.default_draw_id
            
            # Extract participants based on different possible formats
            participants_data = self._extract_participants_data(data)
            
            if not participants_data:
                print("No participant data found in API response")
                return 0
            
            added_count = 0
            seen_participants = set()  # Track duplicates in this batch
            
            for participant_data in participants_data:
                # Create unique key for this batch
                phone_number = self._extract_phone_number(participant_data)
                draw_id = self._extract_draw_id(participant_data, default_draw_id)
                
                if not phone_number or not draw_id:
                    continue
                    
                participant_key = f"{phone_number}-{draw_id}"
                
                if participant_key in seen_participants:
                    print(f"Duplicate in API batch: {phone_number} for draw {draw_id}")
                    continue
                    
                seen_participants.add(participant_key)
                
                if self._add_participant_from_api(participant_data, default_draw_id):
                    added_count += 1
            
            db.session.commit()
            print(f"Added {added_count} participants from API")
            return added_count
            
        except Exception as e:
            db.session.rollback()
            print(f"Error processing API data: {e}")
            return 0
    
    def _extract_participants_data(self, data):
        """Extract participants data from various API response formats"""
        
        print(f"Extracting data from: {data}")
        
        if isinstance(data, dict) and 'phone_numbers' in data:
            phone_numbers = data['phone_numbers']
            if isinstance(phone_numbers, list):
                print(f"Found phone_numbers array with {len(phone_numbers)} numbers")
                return [{"phone_number": phone} for phone in phone_numbers]
        
        if isinstance(data, list) and all(isinstance(item, str) for item in data):
            return [{"phone_number": phone} for phone in data]
        
        elif isinstance(data, list) and all(isinstance(item, dict) for item in data):
            participants = []
            for item in data:
                participant = {}
                
                # Try different possible phone number field names
                phone_fields = ['phone_number', 'phone', 'msisdn', 'number', 'contact']
                for field in phone_fields:
                    if field in item and item[field]:
                        participant['phone_number'] = str(item[field])
                        break
                
                # Try different draw ID field names
                draw_fields = ['draw_id', 'draw', 'raffle_id', 'campaign_id']
                for field in draw_fields:
                    if field in item and item[field]:
                        participant['draw_id'] = item[field]
                        break
                
                if 'phone_number' in participant:
                    participants.append(participant)
            
            return participants
        
        # Format 3: Nested response with data field
        elif isinstance(data, dict) and 'data' in data:
            return self._extract_participants_data(data['data'])
        
        # Format 4: Nested response with results field
        elif isinstance(data, dict) and 'results' in data:
            return self._extract_participants_data(data['results'])
        
        # Format 5: Nested response with participants field
        elif isinstance(data, dict) and 'participants' in data:
            return self._extract_participants_data(data['participants'])
        
        else:
            print(f"Unrecognized API response format: {type(data)}")
            return []
    
    def _add_participant_from_api(self, participant_data, default_draw_id):
        """Add a single participant from API data with flexible format"""
        # Extract phone number using multiple possible field names
        phone_number = None
        phone_fields = ['phone_number', 'phone', 'msisdn', 'number', 'contact']
        
        for field in phone_fields:
            if field in participant_data and participant_data[field]:
                phone_number = str(participant_data[field])
                # Clean phone number (remove spaces, dashes, etc.)
                phone_number = ''.join(filter(str.isdigit, phone_number))
                break
        
        if not phone_number:
            print("No valid phone number found in participant data")
            return False
        
        # Extract draw ID or use default
        draw_id = default_draw_id
        draw_fields = ['draw_id', 'draw', 'raffle_id', 'campaign_id']
        
        for field in draw_fields:
            if field in participant_data and participant_data[field]:
                try:
                    draw_id = int(participant_data[field])
                    break
                except (ValueError, TypeError):
                    continue
        
        # If no draw_id found in data and no default, skip
        if not draw_id:
            print(f"No draw ID specified for participant {phone_number}")
            return False
        
        # Validate draw exists
        draw = Draw.query.get(draw_id)
        if not draw:
            print(f"Draw {draw_id} not found for participant {phone_number}")
            return False
        
        # Check if participant already exists
        existing = Participant.query.filter_by(
            phone_number=phone_number, 
            draw_id=draw_id
        ).first()
        
        if existing:
            print(f"Participant {phone_number} already exists in draw {draw_id}")
            return False
        
        # Add new participant
        participant = Participant(
            phone_number=phone_number,
            draw_id=draw_id,
            source='api',
            is_verified=True,
            added_at=datetime.utcnow()
        )
        
        db.session.add(participant)
        print(f"Added participant {phone_number} from API to draw {draw_id}")
        return True

    def _extract_phone_number(self, participant_data):
        """Extract phone number from participant data"""
        phone_fields = ['phone_number', 'phone', 'msisdn', 'number', 'contact']
        
        for field in phone_fields:
            if field in participant_data and participant_data[field]:
                phone_number = str(participant_data[field])
                return ''.join(filter(str.isdigit, phone_number))
        return None

    def _extract_draw_id(self, participant_data, default_draw_id):
        """Extract draw ID from participant data"""
        draw_fields = ['draw_id', 'draw', 'raffle_id', 'campaign_id']
        
        for field in draw_fields:
            if field in participant_data and participant_data[field]:
                try:
                    return int(participant_data[field])
                except (ValueError, TypeError):
                    continue
        return default_draw_id

# Global API service instance
api_service = APIService()