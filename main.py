from agent import Agent
import sys

if __name__ == "__main__":
    # You can choose which provider and model to use here.
    # Make sure you have the corresponding API key in your .env file.
    # Note: The user requested not to change the model name string.
    ai_agent = Agent(provider="gemini_proxy", model="gemini-2.5-flash-preview-05-20")

    # Check if a query is provided as a command-line argument
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
        # Run once with the argument
        print(f"--- Running test with query: {query} ---")
        ai_agent.run(query)
        print("\n--- Test Run Complete ---\
")
    else:
        # Original interactive loop
        print("--- Stock Analysis Agent ---")
        print("Ask me about a stock, for example: 'Analyze NVIDIA (NVDA) stock'")
        print("Enter 'exit' to quit.")
        
        while True:
            try:
                query = input("> ")
                if query.lower() == 'exit':
                    print("Goodbye!")
                    break
                
                if not query.strip():
                    continue
                    
                result = ai_agent.run(query)
                
                # The final answer is now printed within the agent's run method,
                # so we just add a separator for the next query.
                print("\n------------------------------------\n")

            except KeyboardInterrupt:
                print("\nGoodbye!")
                break