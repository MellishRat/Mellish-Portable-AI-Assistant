import sys

from mellish_ai_bridge.server import mcp, self_test


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    else:
        mcp.run(transport="stdio")
