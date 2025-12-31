from flask import Flask, render_template, request, jsonify
import requests
from bs4 import BeautifulSoup as bs
import re
from textblob import TextBlob
import io
import base64
import matplotlib.pyplot as plt
import random
import threading
import time
import smtplib
from email.mime.text import MIMEText
import pickle
from sklearn.metrics.pairwise import cosine_similarity
from utils.review_scraper import scrape_reviews_from_amazon

app = Flask(__name__)
subscriptions = []

# Load chatbot model
with open("chatbot_nlp_model.pkl", "rb") as f:
    X, vectorizer, responses, queries = pickle.load(f)

# Email sender function
def send_email(to_email, subject, body):
    from_email = "Madhuarruri1@gmail.com"
    from_password = "yaes dpug aovv mwpc"
    msg = MIMEText(body, 'html')
    msg['Subject'] = subject
    msg['From'] = from_email
    msg['To'] = to_email
    try:
        server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
        server.login(from_email, from_password)
        server.sendmail(from_email, to_email, msg.as_string())
        server.quit()
    except Exception as e:
        print("Failed to send email:", e)

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        url = request.form.get('product_url')
        return scrape_and_render(url)
    return render_template('index.html')

def scrape_and_render(url):
    headers = {"User-Agent": "Mozilla/5.0", "Accept-Language": "en-US,en;q=0.5"}
    session = requests.Session()
    session.headers.update(headers)
    web = session.get(url)

    if web.status_code == 200:
        soup = bs(web.content, "html.parser")
        title = soup.title.text.strip().split('|')[0].strip() if soup.title else "Title not found"
        price_tag = soup.find("span", class_="aok-offscreen")
        raw_price = price_tag.text.strip() if price_tag else "Price not found"
        price_match = re.search(r'[\d,]+\.\d{2}', raw_price)
        price = float(price_match.group().replace(',', '')) if price_match else None
        img_tag = soup.find("div", {"id": "imgTagWrapperId", "class": "imgTagWrapper"})
        img_src = img_tag.find("img")["src"] if img_tag and img_tag.find("img") else None
        about_tags = soup.find_all("li", class_="a-spacing-mini")
        about_list = [tag.text.strip() for tag in about_tags] if about_tags else ["About section not found"]
        return render_template('result.html', title=title, price=price, img_src=img_src, about_list=about_list, product_url=url)
    return "Product not found", 404

@app.route('/result')
def result():
    url = request.args.get('product_url')
    if not url:
        return "Product URL missing", 400
    return scrape_and_render(url)

@app.route('/reviews')
def reviews():
    product_url = request.args.get('url', '')
    name = request.args.get("name", "This Product")
    product_name = ' '.join(name.split('|')[0].strip().split()[:3])
    reviews = scrape_reviews_from_amazon(product_url, product_name)

    sentiments = []
    total_rating = 0
    sentiment_counts = {"Positive": 0, "Negative": 0, "Neutral": 0}
    for r in reviews:
        blob = TextBlob(r)
        polarity = blob.sentiment.polarity
        if polarity > 0.1:
            sentiments.append((r, "Positive", 5))
            sentiment_counts["Positive"] += 1
            total_rating += 5
        elif polarity < -0.1:
            sentiments.append((r, "Negative", 1))
            sentiment_counts["Negative"] += 1
            total_rating += 1
        else:
            sentiments.append((r, "Neutral", 3))
            sentiment_counts["Neutral"] += 1
            total_rating += 3

    avg_rating = round(total_rating / len(sentiments), 2)
    labels = list(sentiment_counts.keys())
    sizes = list(sentiment_counts.values())
    colors = ['#2ecc71', '#f39c12', '#e74c3c']
    fig, ax = plt.subplots()
    ax.pie(sizes, labels=labels, colors=colors, autopct='%1.1f%%', startangle=90)
    ax.axis('equal')
    img = io.BytesIO()
    plt.savefig(img, format='png')
    img.seek(0)
    pie_url = base64.b64encode(img.read()).decode('utf8')
    suggestion = "Consider verifying recent reviews before buying." if sentiment_counts['Negative'] > 3000 else "Mostly positive feedback! Worth considering."
    return render_template("reviews.html", top_reviews=sentiments[:5], pie_url=pie_url, stats=sentiment_counts, avg_rating=avg_rating, suggestion=suggestion, product_url=product_url)

@app.route('/subscribe', methods=['POST'])
def subscribe():
    data = request.get_json()
    product_url = data['product_url']
    price_limit = float(data['price_limit'])
    email = data['email']
    title = data['product_title']
    img = data['product_img']
    try:
        headers = {"User-Agent": "Mozilla/5.0", "Accept-Language": "en-US,en;q=0.5"}
        response = requests.get(product_url, headers=headers)
        soup = bs(response.content, "html.parser")
        price_tag = soup.find("span", class_="aok-offscreen")
        raw_price = price_tag.text.strip() if price_tag else None
        price_match = re.search(r'[\d,]+\.\d{2}', raw_price) if raw_price else None
        current_price = float(price_match.group().replace(',', '')) if price_match else None
        if current_price is not None and current_price <= price_limit:
            body = f"""
                <h2> Congrats! Your product is now cheaper!</h2>
                <p><b>{title}</b></p>
                <p>Current Price: ₹{current_price}</p>
                <img src="{img}" width="200"/><br>
                <a href="{product_url}">View on Amazon</a>
            """
            send_email(email, "₹ Price Dropped!", body)
            return "Email sent immediately! Product is below your price limit."
    except Exception as e:
        print("Error in initial price check:", e)
    subscriptions.append({"product_url": product_url, "price_limit": price_limit, "email": email, "product_title": title, "product_img": img})
    return "Saved! You'll get an email when the price drops."

@app.route('/chatbot', methods=['POST'])
def chatbot():
    data = request.get_json()
    user_query = data.get("message", "").strip()
    if not user_query:
        return jsonify({"response": "Please type something to ask."})
    vec = vectorizer.transform([user_query])
    sims = cosine_similarity(vec, X)
    idx = sims.argmax()
    best_match_score = sims[0][idx]
    if best_match_score < 0.3:
        reply = "Sorry, I couldn't understand that. Try asking about product prices or alerts."
    else:
        reply = responses[idx]
    return jsonify({"response": reply})

def price_checker():
    while True:
        time.sleep(600)
        for sub in subscriptions[:]:
            try:
                headers = {"User-Agent": "Mozilla/5.0", "Accept-Language": "en-US,en;q=0.5"}
                response = requests.get(sub['product_url'], headers=headers)
                soup = bs(response.content, "html.parser")
                price_tag = soup.find("span", class_="aok-offscreen")
                raw_price = price_tag.text.strip() if price_tag else None
                price_match = re.search(r'[\d,]+\.\d{2}', raw_price) if raw_price else None
                current_price = float(price_match.group().replace(',', '')) if price_match else None
                if current_price is not None and current_price <= sub['price_limit']:
                    body = f"""
                        <h2>Congrats! Your product is now cheaper!</h2>
                        <p><b>{sub['product_title']}</b></p>
                        <p>Current Price: ₹{current_price}</p>
                        <img src="{sub['product_img']}" width="200"/><br>
                        <a href="{sub['product_url']}">👉 View on Amazon</a>
                    """
                    send_email(sub['email'], "📉 Price Dropped!", body)
                    subscriptions.remove(sub)
            except Exception as e:
                print("Error in periodic check:", e)

if __name__ == '__main__':
    threading.Thread(target=price_checker, daemon=True).start()
    app.run(debug=True)
