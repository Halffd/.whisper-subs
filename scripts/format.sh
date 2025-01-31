#!/bin/bash

# Function to convert decimal seconds to HH:MM:SS,mmm format
convert_timestamp() {
    # Split into seconds and milliseconds
    seconds=${1%.*}
    msec=${1#*.}
    
    # Pad milliseconds to 3 digits
    msec=$(printf "%03d" $(echo "$msec" | sed 's/^0*//' | cut -c1-3))
    
    # Calculate hours, minutes, seconds
    hours=$((seconds / 3600))
    minutes=$(((seconds % 3600) / 60))
    seconds=$((seconds % 60))
    
    # Format output
    printf "%02d:%02d:%02d,%s" $hours $minutes $seconds $msec
}

# Process each .srt file in the current directory and subdirectories
find . -type f -name "*.srt" | while read -r file; do
    echo "Processing $file..."
    
    # Create a temporary file
    temp_file="${file}.tmp"
    
    # Process the file line by line
    while IFS= read -r line || [ -n "$line" ]; do
        # Check if line contains timestamps using grep
        if echo "$line" | grep -E "^[0-9]+\.[0-9]+ *--> *[0-9]+\.[0-9]+$" >/dev/null; then
            # Extract start and end times
            start=$(echo "$line" | awk '{print $1}')
            end=$(echo "$line" | awk '{print $3}')
            
            # Convert timestamps
            start_formatted=$(convert_timestamp "$start")
            end_formatted=$(convert_timestamp "$end")
            
            # Write converted timestamp
            echo "$start_formatted --> $end_formatted" >> "$temp_file"
        else
            # Write unchanged line
            echo "$line" >> "$temp_file"
        fi
    done < "$file"
    
    # Replace original file with formatted version
    mv "$temp_file" "$file"
    echo "Formatted $file"
done

echo "All SRT files have been processed."
