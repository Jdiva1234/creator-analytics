import json
import boto3
import urllib.request
import urllib.parse
from datetime import datetime, timezone

# Configuration
SECRET_NAME = 'youtube-api-key'
CHANNEL_ID = 'UCZj8J7MA0CMvah_036PbA-w'
REGION = 'eu-west-2'
TABLE_NAME = 'creator-stats'

def get_api_key():
    """Fetch the YouTube API key from AWS Secrets Manager."""
    client = boto3.client('secretsmanager', region_name=REGION)
    response = client.get_secret_value(SecretId=SECRET_NAME)
    secret_dict = json.loads(response['SecretString'])
    return secret_dict['api_key']

def fetch_channel_stats(api_key):
    """Call the YouTube Data API for channel statistics."""
    params = urllib.parse.urlencode({
        'part': 'statistics',
        'id': CHANNEL_ID,
        'key': api_key
    })
    url = f'https://www.googleapis.com/youtube/v3/channels?{params}'
    
    with urllib.request.urlopen(url) as response:
        data = json.loads(response.read().decode())
    
    return data

def write_to_dynamodb(stats):
    """Write today's stats into DynamoDB using today's date as the partition key."""
    table = boto3.resource('dynamodb', region_name=REGION).Table(TABLE_NAME)
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    
    item = {
        'date': today,
        'subscribers': int(stats['subscriberCount']),
        'views': int(stats['viewCount']),
        'videos': int(stats['videoCount'])
    }
    
    table.put_item(Item=item)
    return item

def lambda_handler(event, context):
    """Main Lambda entry point."""
    print("Collector Lambda starting...")
    
    api_key = get_api_key()
    print("API key retrieved from Secrets Manager")
    
    data = fetch_channel_stats(api_key)
    stats = data['items'][0]['statistics']
    print(f"Fetched: subs={stats['subscriberCount']}, views={stats['viewCount']}, videos={stats['videoCount']}")
    
    written = write_to_dynamodb(stats)
    print(f"Wrote to DynamoDB: {written}")
    
    return {
        'statusCode': 200,
        'body': json.dumps(written, default=str)
    }
