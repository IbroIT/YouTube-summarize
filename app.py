from flask import Flask, request, jsonify
from flask_cors import CORS
from youtube_transcript_api import YouTubeTranscriptApi
import re

app = Flask(__name__)
CORS(app, resources={
    r"/summarize": {
        "origins": ["https://my-tau-eight.vercel.app"],
        "methods": ["POST"],
        "allow_headers": ["Content-Type"]
    }
})

# Русские стоп-слова
RUS_STOPWORDS = {'и', 'в', 'не', 'что', 'он', 'на', 'я', 'с', 'а', 'то', 'все', 'она', 'так', 'его', 
                'но', 'да', 'ты', 'к', 'у', 'же', 'вы', 'за', 'бы', 'по', 'только', 'ее', 'мне'}

# Английские стоп-слова
ENG_STOPWORDS = {'the', 'and', 'a', 'an', 'in', 'on', 'at', 'for', 'to', 'of', 'with', 'is', 'are', 'was', 'were'}

def get_video_id(url):
    patterns = [
        r'(?:v=|\/)([0-9A-Za-z_-]{11}).*',
        r'youtu\.be\/([0-9A-Za-z_-]{11})'
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def clean_text(text, language):
    text = re.sub(r'\[[^\]]*\]', '', text)  # Удаляем [музыка], [аплодисменты]
    text = re.sub(r'\([^)]*\)', '', text)   # Удаляем (шум), (смех)
    text = re.sub(r'\s+', ' ', text).strip()
    
    # Удаляем стоп-слова в зависимости от языка
    stopwords = RUS_STOPWORDS if language == 'ru' else ENG_STOPWORDS
    words = [word for word in text.split() if word.lower() not in stopwords]
    return ' '.join(words)

def detect_chapters(transcript, language='en'):
    chapters = []
    current_chapter = None
    time_threshold = 120  # 2 минуты между главами
    
    for i, entry in enumerate(transcript):
        text = clean_text(entry['text'], language)
        words = text.split()
        
        # Ищем заглавные слова (потенциальные названия глав)
        if len(words) >= 1 and words[0].istitle() and len(words[0]) > 3:
            if not current_chapter or (entry['start'] - current_chapter['start_time']) > time_threshold:
                if current_chapter:
                    chapters.append(current_chapter)
                current_chapter = {
                    'title': ' '.join(words[:3]),  # Берем первые 3 слова как название
                    'start_time': entry['start'],
                    'content': []
                }
        
        if current_chapter:
            current_chapter['content'].append(text)
    
    if current_chapter:
        chapters.append(current_chapter)
    
    return chapters or [{'title': 'Основное содержание' if language == 'ru' else 'Main Content', 
                        'content': [clean_text(e['text'], language) for e in transcript]}]

def generate_concise_summary(chapters, language='en'):
    summary = f"# Конспект видео\n\n" if language == 'ru' else "# Video Summary\n\n"
    
    for chapter in chapters[:10]:  # Ограничиваем 10 главами
        summary += f"## {chapter['title']}\n"
        
        full_text = ' '.join(chapter['content'])
        sentences = [s for s in re.split(r'[.!?]', full_text) if len(s.split()) > 3]
        
        if len(sentences) > 3:
            selected = [sentences[0], sentences[len(sentences)//2], sentences[-1]]
        else:
            selected = sentences[:3]
        
        for sent in selected:
            if sent.strip():
                summary += f"- {sent.strip()}\n"
        
        summary += "\n"
    
    return summary.strip()

@app.route('/summarize', methods=['POST'])
def summarize():
    data = request.get_json()
    url = data.get('url')
    language = data.get('language', 'en')
    
    if not url:
        return jsonify({'error': 'URL is required'}), 400
    
    video_id = get_video_id(url)
    if not video_id:
        return jsonify({'error': 'Invalid YouTube URL'}), 400
    
    try:
        # Проверяем доступные языки субтитров
        try:
            transcripts = YouTubeTranscriptApi.list_transcripts(video_id)
        except Exception as e:
            return jsonify({
                'error': {
                    'ru': 'Субтитры отключены для этого видео',
                    'en': 'Subtitles are disabled for this video'
                },
                'type': 'NO_SUBTITLES'
            }), 404

        # Для английского сначала пробуем en-US, затем en
        if language == 'en':
            try:
                transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=['en-US'])
            except:
                try:
                    transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=['en'])
                except:
                    return jsonify({
                        'error': {
                            'ru': 'Английские субтитры недоступны для этого видео',
                            'en': 'English subtitles not available for this video'
                        },
                        'type': 'LANGUAGE_NOT_AVAILABLE',
                        'available_languages': [t.language_code for t in transcripts]
                    }), 404
        else:
            try:
                transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=[language])
            except:
                return jsonify({
                    'error': {
                        'ru': 'Русские субтитры недоступны для этого видео',
                        'en': 'Russian subtitles not available for this video'
                    },
                    'type': 'LANGUAGE_NOT_AVAILABLE',
                    'available_languages': [t.language_code for t in transcripts]
                }), 404
        
        chapters = detect_chapters(transcript, language)
        summary = generate_concise_summary(chapters, language)
        return jsonify({'summary': summary})
    
    except Exception as e:
        error_msg = str(e)
        return jsonify({
            'error': {
                'ru': 'Произошла ошибка при обработке видео',
                'en': 'An error occurred while processing the video'
            },
            'details': error_msg,
            'type': 'OTHER_ERROR'
        }), 500

if __name__ == '__main__':
    app.run(debug=True)
