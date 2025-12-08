# Icon Placeholder

To add a custom icon:
1. Create a 256x256 PNG image
2. Convert to ICO format using an online tool or ImageMagick:
   ```
   magick convert icon.png -define icon:auto-resize=256,128,64,48,32,16 icon.ico
   ```
3. Replace this folder's icon.ico with your new icon

For now, the app will use the default Electron icon.
