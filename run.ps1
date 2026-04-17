docker compose up whisperx -d
docker compose exec whisperx python3 -m ensurepip --upgrade
docker compose exec whisperx python3 -m pip install --upgrade pip
docker compose exec whisperx python3 -m pip install -r requirements.txt 
docker compose exec whisperx python3 generate_lyrics.py