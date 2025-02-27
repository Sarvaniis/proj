from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from pymongo import MongoClient
from bson.objectid import ObjectId
from math import radians, sin, cos, sqrt, atan2
from flask import Flask, request, jsonify
from pymongo import MongoClient
import os
import google.generativeai as genai
import base64
import requests
from dotenv import load_dotenv, dotenv_values 
# loading variables from .env file
load_dotenv()

app = Flask(__name__)
CORS(app)  # Enable CORS for frontend access

API_KEY = "your_google_api_key"

UPLOAD_FOLDER = "uploads"
# Create the folder if it doesn't exist
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# Connect to MongoDB (Update the URI if using MongoDB Atlas)
client = MongoClient("mongodb://localhost:27017/")
db = client["zomato"]
collection = db["restaurants"]

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/restaurant-list')
def restaurant_list():
    return render_template('restaurant_list.html')

@app.route('/restaurant-detail/<id>')
def restaurant_detail(id):
    return render_template('restaurant_detail.html', restaurant_id=id)

@app.route('/location-search')
def location_search():
    return render_template('location_search.html')

@app.route('/image-search')
def image_search():
    return render_template('image_search.html')

# 1️⃣ Fetch all restaurants with optional filtering and pagination
@app.route('/restaurants', methods=['GET'])
def get_restaurants():
    # Get filter parameters from request
    city_filter = request.args.get('restaurant.location.city', None)
    spend_filter = request.args.get('average_cost_for_two', None)  # Correct filter field
    cuisine_filter = request.args.get('cuisines', None)
    search_query = request.args.get('search', None)  # Search for restaurant name

    # Pagination parameters
    limit = int(request.args.get('limit', 10))  # Default 10
    page = int(request.args.get('page', 1))     # Default page 1
    skip = (page - 1) * limit

    # Build filter query
    filters = {}

    if city_filter:
        filters["restaurant.location.city"] = {"$regex": city_filter, "$options": "i"}  # Case-insensitive matching
    
    if spend_filter:
        try:
            spend_filter = int(spend_filter)  # Ensure the filter is cast to int (since it's Int32 in MongoDB)
            filters["restaurant.average_cost_for_two"] = {"$lte": int(spend_filter)}  # Filter restaurants where spend <= filter value
        except ValueError:
            return jsonify({"error": "Invalid value for 'average_cost_for_two' filter"}), 400

    if cuisine_filter:
        filters["restaurant.cuisines"] = {"$regex": cuisine_filter, "$options": "i"}

    if search_query:
        filters["restaurant.name"] = {"$regex": search_query, "$options": "i"}
    restaurants = list(collection.find(filters)
         .skip(skip)
         .limit(limit))

    # Add pagination metadata
    total_restaurants = collection.count_documents(filters)
    total_pages = (total_restaurants + limit - 1) // limit  # Calculate total pages

    # Convert _id to string for JSON serialization
    for restaurant in restaurants:
        restaurant["_id"] = str(restaurant["_id"])

    # Return the result with pagination info
    return jsonify({
        "pagination": {
            "limit": limit,
            "page": page,
            "total_pages": total_pages,
            "total_restaurants": total_restaurants
        },
        "restaurants": restaurants
    }), 200

# 2️⃣ Fetch a restaurant by ID
@app.route('/restaurants/<id>', methods=['GET'])
def get_restaurant_by_id(id):
    restaurant = collection.find_one({"_id": ObjectId(id)})
    if restaurant:
        restaurant["_id"] = str(restaurant["_id"])
        return jsonify(restaurant), 200
    return jsonify({"error": "Restaurant not found"}), 404

# 3️⃣ Search for restaurants (by name, location, cuisine)
@app.route('/search', methods=['GET'])
def search_restaurants():
    query = request.args.get('query', '')
    
    print(f"Received query: {query}")  # Debugging print

    results = list(collection.find(
        {"$or": [
            {"restaurant.name": {"$regex": query, "$options": "i"}},
            {"restaurant.location.address": {"$regex": query, "$options": "i"}},
            {"restaurant.cuisines": {"$regex": query, "$options": "i"}}
        ]}
    ))
    for res in results:
        res["_id"] = str(res["_id"])

    if not results:
        return jsonify({"message": "No matching restaurants found"}), 404

    return jsonify({"results": results}), 200

# Haversine function to calculate distance between two lat/lon points
def haversine(lat1, lon1, lat2, lon2):
    R = 6371  # Radius of Earth in KM
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1-a))
    return R * c  # Distance in KM

@app.route('/loca-search', methods=['GET'])
def loca_search():
    lat = float(request.args.get('lat', 0))
    lon = float(request.args.get('lon', 0))
    radius = float(request.args.get('radius', 5))  # Default radius: 5KM

    # Fetch only required fields
    restaurants = list(collection.find({}, {"_id": 1, "restaurant.name": 1, "restaurant.location.latitude": 1, "restaurant.location.longitude": 1}))
    nearby_restaurants = []

    for restaurant in restaurants:
        rest_lat = float(restaurant.get("restaurant", {}).get("location", {}).get("latitude"))
        rest_lon = float(restaurant.get("restaurant", {}).get("location", {}).get("longitude"))

        if rest_lat and rest_lon:
            try:
                rest_lat, rest_lon = float(rest_lat), float(rest_lon)  # Ensure float conversion
                distance = haversine(lat, lon, rest_lat, rest_lon)

                if distance <= radius:
                    restaurant["_id"] = str(restaurant["_id"])  # Convert ObjectId to string
                    restaurant["distance_km"] = round(distance, 2)
                    nearby_restaurants.append(restaurant)

            except ValueError:
                continue  # Skip if conversion fails

    return jsonify({"results": nearby_restaurants}), 200 if nearby_restaurants else 404

API_KEY = "AIzaSyBy8Uyo_VSWTOu2sdQ4rhFDvAxNBizFPnM"  # Ensure this is secure in production

@app.route('/classify', methods=["POST"])
def classify():
    if 'image' not in request.files:
        return {"error": "No image found in request"}, 400

    image = request.files['image']
    
    if image.filename == '':
        return {"error": "No selected file"}, 400

    # Save the image to a folder (e.g., 'uploads/')
    upload_folder = "uploads"
    os.makedirs(upload_folder, exist_ok=True)  # Ensure the folder exists
    image_path = os.path.join(upload_folder, image.filename)
    image.save(image_path)

    # Store the image path in a variable
    saved_image_path = image_path  
    classification_result = classify_cuisine(saved_image_path)
    print(classification_result)
    return {
        "message": "Image saved successfully",
        "path": saved_image_path,
        "classification": classification_result
    }

import google.generativeai as genai

# Set up Gemini API key securely
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

def upload_to_gemini(image_path, mime_type="image/jpeg"):
    """Uploads an image to Gemini for processing."""
    try:
        file = genai.upload_file(image_path, mime_type=mime_type)
        print(f"Uploaded file '{file.display_name}' as: {file.uri}")
        return file
    except Exception as e:
        return f"Error uploading file: {str(e)}"

def classify_cuisine(image_path):
    file = upload_to_gemini(image_path)

    if isinstance(file, str) and file.startswith("Error"):
        return file  # Return error message if upload fails

    # Define food classification prompt
    prompt = """Classify the food in the image into the most suitable category from the following list:
    ['Afghani', 'African', 'American', 'Andhra', 'Arabian', 'Argentine', 'Armenian', 'Asian', 'Asian Fusion',
    'Assamese', 'Australian', 'Awadhi', 'BBQ', 'Bakery', 'Bar Food', 'Belgian', 'Bengali', 'Beverages', 'Bihari',
    'Biryani', 'Brazilian', 'Breakfast', 'British', 'Bubble Tea', 'Burger', 'Burmese', 'Bí_rek', 'Cafe', 'Cajun',
    'Canadian', 'Cantonese', 'Caribbean', 'Charcoal Grill', 'Chettinad', 'Chinese', 'Coffee and Tea',
    'Contemporary', 'Continental', 'Cuban', 'Cuisine Varies', 'Curry', 'Deli', 'Desserts', 'Dim Sum', 'Diner',
    'Drinks Only', 'Durban', 'Dí_ner', 'European', 'Fast Food', 'Filipino', 'Finger Food', 'Fish and Chips',
    'French', 'Fusion', 'German', 'Goan', 'Gourmet Fast Food', 'Greek', 'Grill', 'Gujarati', 'Hawaiian',
    'Healthy Food', 'Hyderabadi', 'Ice Cream', 'Indian', 'Indonesian', 'International', 'Iranian', 'Irish',
    'Italian', 'Izgara', 'Japanese', 'Juices', 'Kashmiri', 'Kebab', 'Kerala', 'Kiwi', 'Korean', 'Latin American',
    'Lebanese', 'Lucknowi', 'Maharashtrian', 'Malay', 'Malaysian', 'Malwani', 'Mangalorean', 'Mediterranean',
    'Mexican', 'Middle Eastern', 'Mineira', 'Mithai', 'Modern Australian', 'Modern Indian', 'Moroccan', 'Mughlai',
    'Naga', 'Nepalese', 'New American', 'North Eastern', 'North Indian', 'Oriya', 'Pakistani', 'Parsi',
    'Patisserie', 'Peranakan', 'Persian', 'Peruvian', 'Pizza', 'Portuguese', 'Pub Food', 'Rajasthani', 'Ramen',
    'Raw Meats', 'Restaurant Cafe', 'Salad', 'Sandwich', 'Scottish', 'Seafood', 'Singaporean', 'Soul Food',
    'South African', 'South American', 'South Indian', 'Southern', 'Southwestern', 'Spanish', 'Sri Lankan',
    'Steak', 'Street Food', 'Sunda', 'Sushi', 'Taiwanese', 'Tapas', 'Tea', 'Teriyaki', 'Tex-Mex', 'Thai',
    'Tibetan', 'Turkish', 'Turkish Pizza', 'Vegetarian', 'Vietnamese', 'Western', 'World Cuisine']

    Return only the best matching cuisine category.
    """

    # Create the model
    model = genai.GenerativeModel(model_name="gemini-2.0-pro-exp-02-05")

    # Start a chat session
    chat_session = model.start_chat(
        history=[
            {"role": "user", "parts": [prompt, file]},
        ]
    )

    # Send message and get response
    response = chat_session.send_message("Classify this food item.")
    
    return response.text.strip()  # Clean response output

if __name__ == '__main__':
    app.run(debug=True)
