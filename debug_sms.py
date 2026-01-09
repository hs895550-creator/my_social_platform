import os
import sys
from uni.client import UniClient

# 配置
UNISMS_ACCESS_KEY_ID = "kFWQ7AsDxdxARQSpaXZQx1uiKdNBWn8fx7kXgPAMAFqXvXiXP"
# Simple Mode (no secret)

def test_sms():
    print("Testing UniSMS...")
    client = UniClient(UNISMS_ACCESS_KEY_ID) # No secret for simple mode
    
    phone = "+855312650654" # User's number from screenshot
    code = "123456"
    
    print(f"Sending to {phone}...")
    
    try:
        # Use client.messages.send instead of client.send
        res = client.messages.send({
            "to": phone,
            "signature": "GlobalAsianElite", 
            "templateId": "pub_verif_basic2", 
            "data": {"code": code}
        })
        print(f"Response Object: {res}")
        print(f"Response Data: {res.data}")
        print(f"Response Code: {getattr(res, 'code', 'Unknown')}")
        print(f"Response Message: {getattr(res, 'message', 'Unknown')}")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_sms()
