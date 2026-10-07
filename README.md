# Data RDTR Sawoo & WebGIS

Repositori ini menyimpan data spasial (shapefile/raster dalam ZIP) untuk penyusunan RDTR Kecamatan Sawoo,
Kabupaten Ponorogo, serta **WebGIS** yang menampilkan seluruh data tersebut.

## WebGIS (`docs/`)
- 101 layer (98 vektor + 3 raster) dikelompokkan dalam 12 grup tematik dengan nama layer yang telah dirapikan.
- Basemap Google Satelit, Hibrida, Jalan, Medan, serta OSM dan Gelap.
- Simbologi per kategori, legenda otomatis, opasitas per layer, label objek, pencarian layer,
  identifikasi objek (klik peta, menampilkan semua layer pada titik tersebut), dan tautan keadaan peta (`#bm=…&l=…`).

### Menjalankan
- **GitHub Pages**: *Settings → Pages → Deploy from a branch →* branch utama, folder **/docs**.
- **Lokal**: `cd docs && python3 -m http.server 8000`, lalu buka <http://localhost:8000>.

### Memperbarui data
Ganti/tambahkan berkas ZIP di root repositori, lalu jalankan:

```bash
pip install pyshp pyproj shapely numpy pillow
python3 tools/build_webgis.py
```

Skrip membaca semua ZIP, mereproyeksikan ke WGS 84, menyederhanakan geometri, membuat `docs/data/*.geojson`
(vektor), `docs/data/*.png` (raster), dan `docs/data/layers.json` (manifest). Nama tampilan, grup, dan warna
setiap layer diatur pada kamus `L` di `tools/build_webgis.py`.

> Geometri pada WebGIS disederhanakan untuk keperluan penayangan; gunakan berkas ZIP asli untuk analisis presisi.
