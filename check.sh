#!/bin/bash
# Check scraper progress
echo "=== Progress ==="
grep "Processing days" logs/run.log | tail -1
echo ""
echo "=== PDFs ==="
ls newspapers/*.pdf 2>/dev/null | wc -l
echo "PDFs generated"
du -sh newspapers/ 2>/dev/null
echo ""
echo "=== Cache ==="
ls cache/ 2>/dev/null
echo ""
echo "=== Last 3 lines ==="
tail -3 logs/run.log
