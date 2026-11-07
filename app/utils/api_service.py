# app/utils/api_service.py
import requests
import time
import json
from threading import Thread, Event
from flask import current_app
from app.extensions import db
from app.models import APIConfig, APIResponseLog
from app.services.import_service import import_entries, rows_from_json
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
            # The raw response body stays in the log, so entries from a failed pull can be recovered.
            db.session.rollback()
            error_msg = f"Error processing API response: {e}"
            print(error_msg)
            response_log.error_message = error_msg
            response_log.success = False
            db.session.add(response_log)
            db.session.commit()
    
    def _process_api_response(self, data):
        """Store one pull as one import batch for the configured draw. Returns entries stored."""
        api_config = APIConfig.query.first()
        if not api_config or not api_config.default_draw_id:
            raise ValueError("No draw selected for API entries")
        rows = rows_from_json(data)
        if not rows:
            return 0
        summary = import_entries(api_config.default_draw_id, rows, source='api',
                                 filename=api_config.endpoint_url)
        return summary.accepted + summary.excluded

# Global API service instance
api_service = APIService()