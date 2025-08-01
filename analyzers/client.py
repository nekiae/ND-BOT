"""API clients for Face++ and AILab services."""

import os
import asyncio
import logging
from typing import Dict, Any, Optional, Tuple
import httpx
import hashlib
import hmac
import time
from urllib.parse import urlencode

logger = logging.getLogger(__name__)


class FacePlusPlusClient:
    """Face++ API client for facial analysis."""
    
    def __init__(self):
        self.api_key = os.getenv("FACEPP_API_KEY")
        self.api_secret = os.getenv("FACEPP_API_SECRET")
        self.base_url = "https://api-us.faceplusplus.com/facepp/v3"
        
        if not self.api_key or not self.api_secret:
            raise ValueError("Face++ API credentials not found in environment")
    
    async def analyze_face(self, image_bytes: bytes) -> Dict[str, Any]:
        """
        Analyze face using Face++ API.
        
        Args:
            image_bytes: Raw image bytes
            
        Returns:
            Analysis results from Face++ API
        """
        url = f"{self.base_url}/detect"
        
        data = {
            "api_key": self.api_key,
            "api_secret": self.api_secret,
            "return_landmark": "1",
            "return_attributes": "beauty,emotion,age,gender,headpose,skinstatus,dark_circle"
        }
        
        files = {"image_file": ("image.jpg", image_bytes, "image/jpeg")}
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.post(url, data=data, files=files)
                response.raise_for_status()
                result = response.json()
                
                if "error_message" in result:
                    raise Exception(f"Face++ API error: {result['error_message']}")
                
                return result
                
            except httpx.TimeoutException:
                raise Exception("Face++ API timeout")
            except httpx.HTTPStatusError as e:
                raise Exception(f"Face++ API HTTP error: {e.response.status_code}")


class AILabClient:
    """AILab API client for facial landmark detection."""
    
    def __init__(self):
        self.api_key = os.getenv("AILAB_API_KEY")
        self.api_secret = os.getenv("AILAB_API_SECRET")
        self.base_url = "https://api.ailabapi.com/api/portrait/effects/face-aging"
        
        if not self.api_key or not self.api_secret:
            raise ValueError("AILab API credentials not found in environment")
    
    def _generate_signature(self, params: Dict[str, str]) -> str:
        """Generate signature for AILab API."""
        # Sort parameters
        sorted_params = sorted(params.items())
        query_string = urlencode(sorted_params)
        
        # Create signature
        signature = hmac.new(
            self.api_secret.encode(),
            query_string.encode(),
            hashlib.sha256
        ).hexdigest()
        
        return signature
    
    async def analyze_face(self, image_bytes: bytes, max_retries: int = 3) -> Dict[str, Any]:
        """
        Analyze face using AILab API with retry logic.
        
        Args:
            image_bytes: Raw image bytes
            max_retries: Maximum number of retries
            
        Returns:
            Analysis results from AILab API
        """
        for attempt in range(max_retries):
            try:
                return await self._analyze_face_single(image_bytes)
            except Exception as e:
                logger.warning(f"AILab API attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(0.8)  # 800ms backoff
                else:
                    raise
    
    async def _analyze_face_single(self, image_bytes: bytes) -> Dict[str, Any]:
        """Single attempt to analyze face with AILab API."""
        timestamp = str(int(time.time()))
        
        params = {
            "apikey": self.api_key,
            "timestamp": timestamp,
            "return_landmark": "106"
        }
        
        # Generate signature
        params["sign"] = self._generate_signature(params)
        
        files = {"image": ("image.jpg", image_bytes, "image/jpeg")}
        
        # Use old route as specified
        url = "https://api.ailabapi.com/rest/160/face_analyze"
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.post(url, data=params, files=files)
                response.raise_for_status()
                result = response.json()
                
                if result.get("errno") != 0:
                    raise Exception(f"AILab API error: {result.get('errmsg', 'Unknown error')}")
                
                return result
                
            except httpx.TimeoutException:
                raise Exception("AILab API timeout")
            except httpx.HTTPStatusError as e:
                raise Exception(f"AILab API HTTP error: {e.response.status_code}")


class DeepSeekClient:
    """DeepSeek API client for report generation."""
    
    def __init__(self):
        self.api_key = os.getenv("DEEPSEEK_API_KEY")
        self.base_url = "https://api.deepseek.com/v1/chat/completions"
        
        if not self.api_key:
            raise ValueError("DeepSeek API key not found in environment")
    
    async def generate_report(
        self, 
        metrics_data: Dict[str, Any], 
        system_prompt: str,
        temperature: float = 0.4
    ) -> str:
        """
        Generate looksmax report using DeepSeek Chat API.
        
        Args:
            metrics_data: Extracted facial metrics
            system_prompt: System prompt with instructions
            temperature: Sampling temperature
            
        Returns:
            Generated report text
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Проанализируй данные: {metrics_data}"}
        ]
        
        data = {
            "model": "deepseek-chat",
            "messages": messages,
            "temperature": temperature,
            "max_tokens": 2000
        }
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                response = await client.post(self.base_url, headers=headers, json=data)
                response.raise_for_status()
                result = response.json()
                
                if "error" in result:
                    raise Exception(f"DeepSeek API error: {result['error']}")
                
                return result["choices"][0]["message"]["content"]
                
            except httpx.TimeoutException:
                raise Exception("DeepSeek API timeout")
            except httpx.HTTPStatusError as e:
                raise Exception(f"DeepSeek API HTTP error: {e.response.status_code}")
