"""
Metadata Generator Module
Auto-generates YouTube metadata (title, description, tags, hashtags)
"""

import json
import logging
import os
from typing import Any, cast

logger = logging.getLogger(__name__)

__all__ = ["MetadataGenerator"]


class MetadataGenerator:
    """
    Auto YouTube Metadata Generator.
    Generates title, description, tags, and hashtags.
    """

    def __init__(self):
        """Initialize metadata generator."""
        # Category-specific titles
        self.titles = {
            "bathroom": "Bathroom Exit Dua | Islamic Prayer",
            "sleep": "Sleep Dua | Bedtime Prayer",
            "food": "Food Dua | Eating Prayer",
            "travel": "Travel Dua | Journey Prayer",
            "morning": "Morning Dua | Daily Prayer",
            "evening": "Evening Dua | Daily Prayer",
            "prayer": "Prayer Dua | Salah Prayer",
            "general": "Islamic Dua | Daily Prayer"
        }

        # Category-specific tags
        self.category_tags = {
            "bathroom": ["Bathroom Dua", "Wudu Dua", "Islamic Hygiene"],
            "sleep": ["Sleep Dua", "Bedtime Dua", "Night Prayer"],
            "food": ["Food Dua", "Eating Dua", "Bismillah"],
            "travel": ["Travel Dua", "Journey Dua", "Safety Prayer"],
            "morning": ["Morning Dua", "Daily Dua", "Morning Prayer"],
            "evening": ["Evening Dua", "Daily Dua", "Evening Prayer"],
            "prayer": ["Prayer Dua", "Salah Dua", "Islamic Prayer"],
            "general": ["General Dua", "Daily Dua", "Islamic Prayer"]
        }

        # Base tags
        self.base_tags = [
            "Islamic Dua",
            "Urdu Dua",
            "Arabic Dua",
            "Prayer",
            "Muslim",
            "Islam",
            "Dua",
            "Duain"
        ]

    def generate(self, arabic_text: str, urdu_text: str, category: str) -> dict:
        """
        Generate YouTube metadata.
        
        Args:
            arabic_text: Arabic dua text
            urdu_text: Urdu translation
            category: Dua category
            
        Returns:
            YouTube metadata dictionary
        """
        title = self.generate_title(category)
        description = self.generate_description(arabic_text, urdu_text, category)
        tags = self.generate_tags(category)
        hashtags = self.generate_hashtags(category)

        return {
            "title": title,
            "description": description,
            "tags": tags,
            "hashtags": hashtags
        }

    def generate_title(self, category: str) -> str:
        """
        Generate YouTube title.
        
        Args:
            category: Dua category
            
        Returns:
            YouTube title
        """
        return self.titles.get(category, "Islamic Dua | Prayer")

    def generate_description(self, arabic_text: str, urdu_text: str,
                             category: str) -> str:
        """
        Generate YouTube description.
        
        Args:
            arabic_text: Arabic dua text
            urdu_text: Urdu translation
            category: Dua category
            
        Returns:
            YouTube description
        """
        description = f"""
Islamic Dua Video

Arabic: {arabic_text}

Urdu: {urdu_text}

Category: {category.title()}

---

Subscribe for more Islamic content!
Like & Share if you benefited from this dua.

---

#IslamicDua #UrduDua #ArabicDua #Prayer #Muslim #Islam #Dua #Duain
"""
        return description.strip()

    def generate_tags(self, category: str) -> list[str]:
        """
        Generate YouTube tags.
        
        Args:
            category: Dua category
            
        Returns:
            List of tags
        """
        category_specific = self.category_tags.get(category, [])
        return self.base_tags + category_specific

    def generate_hashtags(self, category: str) -> str:
        """
        Generate YouTube hashtags.
        
        Args:
            category: Dua category
            
        Returns:
            Hashtags string
        """
        base_hashtags = "#IslamicDua #UrduDua #ArabicDua #Prayer #Muslim"

        category_hashtags = {
            "bathroom": "#BathroomDua #Wudu",
            "sleep": "#SleepDua #BedtimePrayer",
            "food": "#FoodDua #Bismillah",
            "travel": "#TravelDua #SafetyPrayer",
            "morning": "#MorningDua #DailyPrayer",
            "evening": "#EveningDua #DailyPrayer",
            "prayer": "#PrayerDua #Salah",
            "general": "#DailyDua #IslamicPrayer"
        }

        specific = category_hashtags.get(category, "")

        if specific:
            return f"{base_hashtags} {specific}"
        else:
            return base_hashtags

    def save_metadata(self, metadata: dict, output_path: str):
        """
        Save metadata to JSON file.
        
        Args:
            metadata: Metadata dictionary
            output_path: Path to save file
        """
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

    def load_metadata(self, metadata_path: str) -> dict[str, Any] | None:
        """
        Load metadata from JSON file.
        
        Args:
            metadata_path: Path to metadata file
            
        Returns:
            Metadata dictionary
        """
        if not os.path.exists(metadata_path):
            return None

        with open(metadata_path, encoding='utf-8') as f:
            return cast(dict[str, Any], json.load(f))


# Test function
if __name__ == "__main__":
    print("Testing Metadata Generator...")

    generator = MetadataGenerator()

    # Test metadata generation
    test_arabic = "بِسْمِ اللَّهِ الرَّحْمَنِ الرَّحِيمِ"
    test_urdu = "اللہ کے نام سے شروع جو بہت مہربان ناہے"

    categories = ["bathroom", "sleep", "food", "travel", "general"]

    for category in categories:
        print(f"\n{category.upper()}:")
        metadata = generator.generate(test_arabic, test_urdu, category)

        print(f"  Title: {metadata['title']}")
        print(f"  Tags: {metadata['tags'][:5]}...")
        print(f"  Hashtags: {metadata['hashtags'][:50]}...")

    print("\nMetadata Generator Test Complete!")
