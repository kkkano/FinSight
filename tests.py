import unittest
from tools import get_stock_price, get_company_news, get_company_info, search

class TestTools(unittest.TestCase):

    def test_get_stock_price(self):
        """Tests the get_stock_price function."""
        price_str = get_stock_price("AAPL")
        self.assertTrue("The current stock price for AAPL is" in price_str)

    def test_get_stock_price_invalid(self):
        """Tests the get_stock_price function with an invalid ticker."""
        error_str = get_stock_price("INVALIDTICKER")
        self.assertTrue("Error: Could not find price data for ticker 'INVALIDTICKER'" in error_str)

    def test_get_company_news(self):
        """Tests the get_company_news function."""
        news_str = get_company_news("AAPL")
        self.assertTrue("title" in news_str)

    def test_get_company_info(self):
        """Tests the get_company_info function."""
        info_str = get_company_info("AAPL")
        self.assertTrue("longName" in info_str)

    def test_search(self):
        """Tests the search function."""
        search_results = search("Apple Inc.")
        self.assertTrue("title" in search_results)

if __name__ == '__main__':
    unittest.main()
