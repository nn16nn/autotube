# AutoTube

Тақырып жазасың, бағдарлама өзі сценарий жазады, сурет пен дауыс жасайды, видеоға жинайды және YouTube-қа жүктейді (қаласаң уақыт кестесімен).

Тек тегін қызметтер: сценарий (Pollinations / Gemini / Groq тегін кілті), сурет (Pollinations), дауыс (edge-tts, `kk-KZ`), монтаж (ffmpeg).

## Render-ге орнату

1. Папканы GitHub репоға салыңыз (мысалы `nn16nn/autotube`).
2. Render → New → Blueprint → репоны таңдаңыз (`render.yaml` бәрін өзі баптайды).
3. Environment:
   - `APP_PASSWORD`: кіру құпиясөзі (міндетті, онсыз сайт ашылмайды)
   - `PUBLIC_URL`: `https://<сіздің-сервис>.onrender.com`
   - `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`: YouTube үшін (төменде)
   - `GEMINI_API_KEY` немесе `GROQ_API_KEY`: міндетті емес, тегін кілт. Қазақша сапасы жақсырақ болады.

## YouTube қосу

1. console.cloud.google.com → жаңа жоба → **YouTube Data API v3** қосу.
2. OAuth consent screen → Test users-ке өз Gmail-іңізді қосыңыз.
3. Credentials → OAuth client ID → **Web application**. Authorized redirect URI:
   `https://<сіздің-сервис>.onrender.com/youtube/callback`
4. Client ID мен Secret-ті Render-ге қойыңыз, сайтта «YouTube қосу» батырмасын басыңыз.

## Маңызды шектеулер

- **Жабық режим**: тексерілмеген Google жобасымен жүктелген видеолар YouTube-та міндетті түрде `private` болып қалады. Ашық шығару үшін YouTube API Services Audit өту керек (Google-дің формасы). Дайын видеоны Studio-дан қолмен ашуға да болады.
- **Render free** жоспары 15 минут бос тұрса ұйықтайды, ұзын видео жасау үзілуі мүмкін. `starter` жоспары (диск үшін де керек) тұрақты жұмыс істейді.
- Кесте: уақыт көрсетсеңіз, видео бірден жүктеліп, YouTube өзі сол уақытта жариялайды. Серверді сол сәтте қосулы ұстаудың керегі жоқ.
- Видеолар «AI арқылы жасалған (synthetic media)» деп белгіленіп жүктеледі. Монетизация үшін бір үлгімен жаппай шығарылған, адам араласпаған контент қауіпті: тақырыптарды өзіңіз таңдап, дайын видеоны қарап шығып жүріңіз.
- Тегін Pollinations кейде баяу немесе тоқтап қалады: сурет шықпаса, бағдарлама градиент фонмен жалғастырады. Қазақша дауысы 2 ғана (Дәулет, Айгүл).

## Жергілікті іске қосу

```bash
pip install -r requirements.txt
python app.py        # http://localhost:5000
DEMO=1 python app.py # интернетсіз тест: жасанды сценарий, градиент сурет, үнсіз дыбыс
```

## Құрылым

| Файл | Міндеті |
|---|---|
| `app.py` | Flask сервер, кіру, API, фондық жұмысшы |
| `pipeline.py` | сценарий → сурет → дауыс → монтаж → жүктеу |
| `llm.py` | сценарий жазу (Gemini / Groq / Pollinations) |
| `media.py` | сурет, edge-tts, субтитр, ffmpeg |
| `youtube.py` | OAuth және YouTube жүктеу |
| `db.py` | SQLite кезек |
