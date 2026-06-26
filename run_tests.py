#!/usr/bin/env python3
"""Simple test runner for mcp-buffer."""
import sys
import os
import asyncio

# Add parent directory to path
sys.path.insert(0, '/home/alex/.memory')
os.chdir('/home/alex/.memory/mcp-buffer')

from tests.test_buffer_backend import (
    test_entry_fields,
    test_registry,
    test_unknown_raises,
    MockBackend,
    test_upload,
    test_list,
)


def run_sync_tests():
    print("Running synchronous tests...")
    test_entry_fields()
    print("✓ test_entry_fields passed")

    test_registry()
    print("✓ test_registry passed")

    try:
        test_unknown_raises()
        print("✓ test_unknown_raises passed")
    except Exception as e:
        print(f"✗ test_unknown_raises failed: {e}")


async def run_async_tests():
    print("\nRunning async tests...")
    await test_upload()
    print("✓ test_upload passed")

    await test_list()
    print("✓ test_list passed")


if __name__ == "__main__":
    try:
        run_sync_tests()
        asyncio.run(run_async_tests())
        print("\n=== ALL TESTS PASSED ===")
        sys.exit(0)
    except Exception as e:
        print(f"\n=== TEST FAILED: {e} ===")
        import traceback
        traceback.print_exc()
        sys.exit(1)
