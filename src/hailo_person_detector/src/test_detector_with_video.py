import requests



requests.post('http://localhost:3000/submit/video_url', json={"video_url": "https://youtu.be/zPre8MgmcHY"})
# requests.post('http://localhost:3000/submit/video_url', json={"video_url": "https://youtu.be/McIzCQnqXmg"})

curl -X POST http://localhost:3000/submit/image \
  -H "Content-Type: application/json" \
  -d '{"camera_id":"cam-1","filename":"/home/pi/p1.jpeg"}'
