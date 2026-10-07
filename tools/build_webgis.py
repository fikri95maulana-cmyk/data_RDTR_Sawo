#!/usr/bin/env python3
"""Bangun data WebGIS RDTR Sawoo dari arsip shapefile (*.zip) di root repositori.

Keluaran (folder docs/):
  data/<kunci>.geojson   -> layer vektor (WGS84, disederhanakan)
  data/<kunci>.png       -> layer raster (WGS84)
  data/layers.json       -> manifest: grup, nama tampilan, simbologi, legenda

Pemakaian:  python3 tools/build_webgis.py
Kebutuhan:  pip install pyshp pyproj shapely numpy pillow
"""
import collections
import glob
import json
import math
import os
import re
import sys
import tempfile
import zipfile

import numpy as np
import shapefile
from PIL import Image
from pyproj import CRS, Transformer
from shapely.geometry import mapping, shape
from shapely import force_2d

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "data")
MAX_BYTES = 1_200_000  # batas ukuran geometri per layer sebelum disederhanakan lebih kuat

# ----------------------------------------------------------------- palet warna
R5 = ["#1a9641", "#a6d96a", "#ffffbf", "#fdae61", "#d7191c"]
R4 = ["#1a9641", "#a6d96a", "#fdae61", "#d7191c"]
R3 = ["#1a9641", "#fee08b", "#d7191c"]
R2 = ["#fee08b", "#d7191c"]
R3R = R3[::-1]
SUIT = ["#1a9850", "#91cf60", "#fee08b", "#fc8d59", "#b2182b"]
YLORRD = ["#ffffb2", "#fecc5c", "#fd8d3c", "#f03b20", "#bd0026"]
BLUES = ["#c6dbef", "#6baed6", "#2171b5", "#08306b"]
QUAL = ["#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4", "#46f0f0", "#f032e6",
        "#bcf60c", "#fabebe", "#008080", "#9a6324", "#800000", "#aaffc3", "#808000",
        "#000075", "#e6beff"]

LAND_RULES = [  # (kata kunci, warna) untuk penggunaan tanah
    ("kampung", "#ff8a65"), ("permukiman", "#ff8a65"), ("sawah", "#aeea00"),
    ("padi", "#aeea00"), ("kebun", "#7cb342"), ("hutan belukar", "#43a047"),
    ("hutan", "#1b5e20"), ("semak", "#c0ca33"), ("tegalan", "#e6d96b"),
    ("ladang", "#e6d96b"), ("sungai", "#29b6f6"), ("danau", "#29b6f6"),
    ("terbuka", "#d7b98e"), ("tambang", "#8d6e63"),
]


def land_color(name):
    n = name.lower()
    for k, c in LAND_RULES:
        if k in n:
            return c
    return "#b0bec5"


def ramp(values, colors):
    return {v: c for v, c in zip(values, colors)}


# --------------------------------------------------------------- grup layer
G_ADM = "Administrasi & Batas Wilayah"
G_PEND = "Kependudukan & Sosial Ekonomi"
G_WP = "Analisis Wilayah Perencanaan"
G_LAHAN = "Kesesuaian & Kemampuan Lahan"
G_BENCANA = "Kebencanaan & Risiko"
G_FISIK = "Fisik Dasar: Topografi, Geologi & Tanah"
G_AIR = "Hidrologi, Sungai & Iklim"
G_GUNA = "Penggunaan Lahan & Vegetasi"
G_INFRA = "Transportasi & Utilitas"
G_SARANA = "Sarana & Lingkungan Terbangun"
G_KAWASAN = "Kawasan Hutan, Pertanahan & Pertambangan"
G_RASTER = "Data Raster"

GROUP_ORDER = [G_ADM, G_PEND, G_WP, G_LAHAN, G_BENCANA, G_FISIK, G_AIR, G_GUNA,
               G_INFRA, G_SARANA, G_KAWASAN, G_RASTER]

HAZ_LEVELS5 = ["Sangat Rendah", "Rendah", "Sedang", "Tinggi", "Sangat Tinggi"]
SUIT_ORDER = ["S1 - Sangat sesuai", "S2 - Sesuai", "S3 - Sesuai marginal",
              "N - Tidak sesuai"]

# stem shapefile -> (grup, nama tampilan, gaya)
# gaya:  {"t":"cat","f":kolom/templat,"c":{nilai:warna|(warna,tebal,putus)},"auto":True}
#        {"t":"one","c":warna}   {"t":"outline","c":warna,"w":tebal}
#        {"t":"quant","f":kolom,"n":kelas,"c":ramp,"unit":"jiwa"}
#        opsi: "label": kolom label peta, "drop": {kolom:[nilai dibuang]}
L = {
    # --- administrasi
    "ADMINISTRASI_AR_DESAKEL": (G_ADM, "Batas Desa/Kelurahan", {"t": "outline", "c": "#ffd600", "w": 2, "label": "WADMKD"}),
    "ADMINISTRASI_AR_DESAKEL_25K": (G_ADM, "Batas Desa/Kelurahan (Skala 1:25.000)", {"t": "outline", "c": "#ffab00", "w": 1.6, "label": "NAMOBJ"}),
    "ADMINISTRASI_AR_KECAMATAN": (G_ADM, "Batas Kecamatan Sawoo", {"t": "outline", "c": "#ff5722", "w": 3}),
    "ADMINISTRASI_AR_KECAMATAN_25K": (G_ADM, "Batas Kecamatan Sawoo (Skala 1:25.000)", {"t": "outline", "c": "#ff7043", "w": 2.4}),
    "ADMINISTRASI_AR_KECAMATAN_SATUPETA": (G_ADM, "Batas Kecamatan Sawoo (Kebijakan Satu Peta)", {"t": "outline", "c": "#f4511e", "w": 2}),
    "ADMINISTRASI_AR_KABKOTA_25K": (G_ADM, "Batas Kabupaten Ponorogo (Skala 1:25.000)", {"t": "outline", "c": "#e91e63", "w": 3}),
    "ADMINISTRASI_AR_KABKOTA_50K": (G_ADM, "Batas Kabupaten Ponorogo (Skala 1:50.000)", {"t": "outline", "c": "#ec407a", "w": 2.4}),
    "ADMINISTRASI_AR_KABKOTA_SATUPETA": (G_ADM, "Batas Kabupaten Ponorogo (Kebijakan Satu Peta)", {"t": "outline", "c": "#d81b60", "w": 2}),
    "ADMINISTRASI_LN": (G_ADM, "Garis Batas Administrasi (Kecamatan & Desa)", {"t": "one", "c": "#ffffff", "w": 2, "dash": "6 4"}),
    "ADMINISTRASI_LN_KABKOTA_25K": (G_ADM, "Garis Batas Ponorogo – Trenggalek (Skala 1:25.000)", {"t": "one", "c": "#ff80ab", "w": 3, "dash": "8 4"}),
    "ADMINISTRASI_LN_KABKOTA_SATUPETA": (G_ADM, "Garis Batas Ponorogo – Trenggalek (Kebijakan Satu Peta)", {"t": "one", "c": "#f06292", "w": 2.4, "dash": "8 4"}),
    "TOPONIMI_PT_25K": (G_ADM, "Toponimi (Nama Rupabumi)", {"t": "cat", "f": "REMARK", "auto": True, "label": "NAMOBJ"}),
    # --- kependudukan
    "KEPENDUDUKAN_DESA_AR": (G_PEND, "Jumlah Penduduk per Desa Tahun 2025 (BPS)", {"t": "quant", "f": "PEND25", "n": 5, "c": YLORRD, "unit": "jiwa", "label": "DESA"}),
    "KEPADATAN_DASIMETRIK_GRID100M_AR": (G_PEND, "Kepadatan Penduduk Dasimetrik (Grid 100 m)", {"t": "cat", "f": "KET", "c": ramp(["Sangat rendah (< 10 jiwa/ha)", "Rendah (10-25)", "Sedang (25-50)"], YLORRD[:1] + YLORRD[2:4]), "nostroke": True}),
    "PODES_AR_SATUPETA": (G_PEND, "Potensi Desa (PODES) per Kecamatan", {"t": "cat", "f": "kecamatan", "auto": True, "label": "kecamatan"}),
    "KLASIFIKASIDESA_AR": (G_PEND, "Klasifikasi Desa (Perdesaan/Perkotaan)", {"t": "cat", "f": "KLS_BPS20", "c": {"Perkotaan": "#e53935", "Perdesaan": "#7cb342"}, "label": "DESA"}),
    # --- wilayah perencanaan
    "ORDE_DESA_AR": (G_WP, "Orde Pusat Pelayanan Desa", {"t": "cat", "f": "Orde {ORDE}", "c": ramp(["Orde I", "Orde II", "Orde III"], ["#b2182b", "#f4a582", "#92c5de"]), "label": "WADMKD"}),
    "KONSENTRASIKEGIATAN_AR": (G_WP, "Konsentrasi Kegiatan", {"t": "cat", "f": "NAMA", "c": ramp(["Konsentrasi Rendah", "Konsentrasi Sedang", "Konsentrasi Tinggi"], YLORRD[:1] + YLORRD[2:4])}),
    "HOTSPOT_GISTAR_GRID100M_AR": (G_WP, "Hotspot Kegiatan (Getis-Ord Gi*, Grid 100 m)", {"t": "cat", "f": "Gi_Bin", "labels": {"0": "Tidak signifikan", "1": "Hotspot (kepercayaan 90%)", "2": "Hotspot (kepercayaan 95%)", "3": "Hotspot (kepercayaan 99%)"}, "c": {"0": "#cfd8dc", "1": "#fdae61", "2": "#f46d43", "3": "#a50026"}, "nostroke": True}),
    "LQ_KEGIATAN_DESA_AR": (G_WP, "Location Quotient (LQ) Kegiatan per Desa", {"t": "quant", "f": "LQ", "n": 4, "c": YLORRD[:1] + YLORRD[2:5], "unit": "LQ", "label": "WADMKD"}),
    "TITIK_KEGIATAN_PT": (G_WP, "Titik Kegiatan (Pusat Kegiatan Masyarakat)", {"t": "cat", "f": "KATEGORI", "auto": True}),
    "AKSES_DESA_AR": (G_WP, "Keterjangkauan Desa terhadap Skenario Ruas Terputus", {"t": "cat", "f": "SKB_STATUS", "c": {"TERISOLASI (tidak terjangkau)": "#d32f2f", "Tidak/sedikit terdampak": "#66bb6a"}, "label": "WADMKD"}),
    "AKSESIBILITAS_AR": (G_WP, "Aksesibilitas Wilayah", {"t": "cat", "f": "NAMA", "c": ramp(["Aksesibilitas Tinggi", "Aksesibilitas Sedang", "Aksesibilitas Rendah"], R3)}),
    "SERVICEAREA_PUSATWP_AR": (G_WP, "Area Layanan Pusat Wilayah Perencanaan (Waktu Tempuh)", {"t": "cat", "f": "NAMA", "c": ramp(["0-5 menit", "5-10 menit", "10-15 menit", "15-30 menit", "> 30 menit"], R5)}),
    "SKENARIO_RUAS_TERPUTUS_LN": (G_WP, "Skenario Ruas Jalan Terputus", {"t": "cat", "f": "FUNGSI", "c": {"Jalan Nasional": ("#d32f2f", 4), "Jalan Lokal": ("#f57c00", 3), "Jalan Lingkungan": ("#fbc02d", 2.5), "Jalan Lain": ("#ffffff", 1.6), "Jalan Setapak": ("#b0bec5", 1.2, "3 3")}}),
    "FUNGSIKAWASAN_AR": (G_WP, "Fungsi Kawasan (Lindung, Penyangga, Budi Daya)", {"t": "cat", "f": "NAMA", "c": ramp(["Kawasan Lindung", "Kawasan Penyangga", "Kawasan Budi Daya"], ["#1b7837", "#a6dba0", "#f4a460"]), "nostroke": True}),
    # --- kesesuaian lahan
    "KESESUAIANPANGAN_AR": (G_LAHAN, "Kesesuaian Lahan Pertanian Pangan", {"t": "cat", "f": "NAMA", "c": ramp(SUIT_ORDER + ["Tidak dievaluasi (terbangun/badan air)"], SUIT[:4] + ["#bdbdbd"]), "nostroke": True}),
    "KESESUAIANPERMUKIMAN_AR": (G_LAHAN, "Kesesuaian Lahan Permukiman", {"t": "cat", "f": "NAMA", "c": ramp(["S1 - Sangat sesuai", "S2 - Sesuai", "S3 - Sesuai marginal", "N - Tidak sesuai", "N - Kendala mutlak"], SUIT), "nostroke": True}),
    "KEMAMPUANLAHAN_AR_RTRW": (G_LAHAN, "Kemampuan Lahan (Kemampuan Pengembangan)", {"t": "cat", "f": "KlasfSKL", "c": ramp(["Kemampuan Pengembangan Rendah", "Kemampuan Pengembangan Sedang", "Kemampuan Pengembangan Tinggi"], R3)}),
    "LAHANBAKUSAWAH_AR_50K": (G_LAHAN, "Lahan Baku Sawah (Skala 1:50.000)", {"t": "one", "c": "#9ccc65"}),
    # --- kebencanaan
    "RAWANBANJIR_AR": (G_BENCANA, "Kerawanan Banjir", {"t": "cat", "f": "NAMA", "c": ramp(["Kerawanan Rendah", "Kerawanan Sedang", "Kerawanan Tinggi"], R3), "nostroke": True}),
    "RAWANLONGSOR_AR": (G_BENCANA, "Kerawanan Longsor", {"t": "cat", "f": "NAMA", "c": ramp(["Kerawanan Rendah", "Kerawanan Sedang", "Kerawanan Tinggi"], R3), "nostroke": True}),
    "KERENTANAN_AR": (G_BENCANA, "Kerentanan Bencana", {"t": "cat", "f": "NAMA", "c": ramp(["Kerentanan Rendah", "Kerentanan Sedang"], R2), "nostroke": True}),
    "RISIKOBENCANA_AR": (G_BENCANA, "Risiko Bencana (Banjir & Longsor)", {"t": "cat", "f": "NAMA", "c": ramp(["Risiko Rendah", "Risiko Sedang", "Risiko Tinggi"], R3), "nostroke": True}),
    "KRB_BANJIR_AR_RTRW": (G_BENCANA, "Kawasan Rawan Bencana Banjir (RTRW)", {"t": "cat", "f": "BANJIR", "c": ramp(HAZ_LEVELS5, R5)}),
    "KRB_GEMPABUMI_AR_RTRW": (G_BENCANA, "Kawasan Rawan Bencana Gempa Bumi (RTRW)", {"t": "cat", "f": "GEMPABUMI", "c": ramp(HAZ_LEVELS5, R5)}),
    "KRB_GEMPABUMI_AR_SATUPETA": (G_BENCANA, "Kawasan Rawan Bencana Gempa Bumi (Kebijakan Satu Peta)", {"t": "cat", "f": "kelas", "c": {"Kawasan Rawan Bencana Gempabumi Menengah": "#fdae61", "Kawasan Rawan Bencana Gempabumi Tinggi": "#d7191c"}}),
    "KRB_GUNUNGAPI_AR_RTRW": (G_BENCANA, "Kawasan Rawan Bencana Gunung Api (RTRW)", {"t": "cat", "f": "GUNUNGAPI", "c": ramp(HAZ_LEVELS5, R5)}),
    "KRB_LIKUEFAKSI_AR_RTRW": (G_BENCANA, "Kawasan Rawan Bencana Likuefaksi (RTRW)", {"t": "cat", "f": "LIFUEKFASI", "c": ramp(HAZ_LEVELS5, R5)}),
    "KERENTANANLIKUEFAKSI_AR_100K": (G_BENCANA, "Zona Kerentanan Likuefaksi (Skala 1:100.000)", {"t": "cat", "f": "namobj", "auto": True}),
    "ZKGT_AR_SATUPETA": (G_BENCANA, "Zona Kerentanan Gerakan Tanah", {"t": "cat", "f": "namobj", "c": ramp(["Zona Kerentanan Gerakan Tanah Sangat Rendah", "Zona Kerentanan Gerakan Tanah Rendah", "Zona Kerentanan Gerakan Tanah Menengah", "Zona Kerentanan Gerakan Tanah Tinggi"], R4)}),
    "RAWANEROSI_AR_SATUPETA": (G_BENCANA, "Kerawanan Erosi", {"t": "cat", "f": "klas_erosi", "c": ramp(["<= 15 Ton/Ha/Tahun", "> 15 - 60 Ton/Ha/Tahun", "> 60 - 180 Ton/Ha/Tahun", "> 180 - 480 Ton/Ha/Tahun", "> 480 Ton/Ha/Tahun"], R5)}),
    "RAWANKARHUTLA_AR_250K": (G_BENCANA, "Kerawanan Kebakaran Hutan dan Lahan", {"t": "cat", "f": "kelas", "c": ramp(["Sedang", "Tinggi", "Sangat Tinggi"], ["#fee08b", "#fc8d59", "#d73027"])}),
    "SEISMISITAS_PT_SATUPETA": (G_BENCANA, "Titik Seismisitas (Kejadian Gempa)", {"t": "one", "c": "#d500f9", "r": 8}),
    "PATAHANAKTIF_LN_50K": (G_BENCANA, "Patahan Aktif", {"t": "one", "c": "#ff1744", "w": 3, "dash": "8 4"}),
    # --- fisik dasar
    "KEMIRINGANLERENG_AR_RTRW": (G_FISIK, "Kemiringan Lereng", {"t": "cat", "f": "{Keterangan} ({Slope})", "c": ramp(["Datar (0-2%)", "Berombak (2-5%)", "Berbukit (5-15%)", "Curam (15-40%)", "Sangat Curam (>40%)"], R5), "nostroke": True}),
    "TOPOGRAFI_AR_RTRW": (G_FISIK, "Topografi (Ketinggian)", {"t": "cat", "f": "Topografi", "c": {"0-500 Mpdl": "#a1d99b", "500-1000 Mpdl": "#8c6d31"}}),
    "KONTUR_LN_25K": (G_FISIK, "Garis Kontur (Skala 1:25.000)", {"t": "one", "c": "#c8a165", "w": 0.8}),
    "SPOTHEIGHT_PT_25K": (G_FISIK, "Titik Tinggi (Spot Height)", {"t": "one", "c": "#ffffff", "r": 3.5, "label": "ELEVAS"}),
    "GEOLOGI_AR_RTRW": (G_FISIK, "Geologi (Formasi Batuan, RTRW)", {"t": "cat", "f": "NAME", "auto": True}),
    "GEOLOGI_AR_SATUPETA": (G_FISIK, "Geologi (Kebijakan Satu Peta)", {"t": "cat", "f": "namobj", "auto": True}),
    "STRUKTURGEOLOGI_LN_SATUPETA": (G_FISIK, "Struktur Geologi (Sesar & Kelurusan)", {"t": "cat", "f": "klsstr", "c": {"Sesar": ("#e53935", 2.5), "Sesar Diperkirakan": ("#ff8a65", 2, "6 4"), "Not Defined": ("#fff176", 1.6, "2 4")}}),
    "KBAK_AR_SATUPETA": (G_FISIK, "Kawasan Bentang Alam Karst (KBAK)", {"t": "cat", "f": "namobj", "auto": True}),
    "MINERALNONLOGAM_PT_SATUPETA": (G_FISIK, "Potensi Mineral Non-Logam", {"t": "cat", "f": "namobj", "auto": True, "r": 8}),
    "JENISTANAH_AR_RTRW": (G_FISIK, "Jenis Tanah", {"t": "cat", "f": "KET", "auto": True}),
    # --- hidrologi & iklim
    "SUNGAI_AR_25K": (G_AIR, "Sungai (Area/Polygon)", {"t": "one", "c": "#29b6f6"}),
    "SUNGAI_LN_25K": (G_AIR, "Sungai (Garis)", {"t": "cat", "f": "REMARK", "c": {"Sungai": ("#0288d1", 2.4), "Alur Sungai": ("#4fc3f7", 1.5), "Sungai Satu Garis": ("#81d4fa", 1)}}),
    "AIRTANAH_PT_SATUPETA": (G_AIR, "Sumur Air Tanah", {"t": "cat", "f": "nm_inf", "auto": True, "r": 8}),
    "CAT_AR_250K": (G_AIR, "Cekungan Air Tanah (CAT)", {"t": "cat", "f": "namobj", "auto": True}),
    "HIDROGEOLOGI_LITOLOGI_AR_SATUPETA": (G_AIR, "Hidrogeologi: Litologi Akuifer", {"t": "cat", "f": "litologi", "auto": True}),
    "HIDROGEOLOGI_PRODUKTIVITAS_AR_SATUPETA": (G_AIR, "Hidrogeologi: Produktivitas Akuifer", {"t": "cat", "f": "prod", "auto": True}),
    "KETERSEDIAANAIR_AR_SATUPETA": (G_AIR, "Ketersediaan Air (Wilayah Sungai)", {"t": "cat", "f": "nm_inf", "auto": True}),
    "NERACASDA_AR_50K": (G_AIR, "Neraca Sumber Daya Air", {"t": "cat", "f": "kls_nrcair", "c": {"Surplus": "#66bb6a", "Defisit": "#ef5350"}}),
    "CURAHHUJAN_AR_SATUPETA": (G_AIR, "Curah Hujan Tahunan", {"t": "cat", "f": "crhhjn", "c": ramp(["1500 - 2000 mm", "2000 - 2500 mm"], BLUES[:2])}),
    "POTENSIENERGIANGIN_AR_SATUPETA": (G_AIR, "Potensi Energi Angin", {"t": "cat", "f": "poenag", "auto": True}),
    "POTENSIENERGISURYA_AR_SATUPETA": (G_AIR, "Potensi Energi Surya", {"t": "cat", "f": "poenmt", "auto": True}),
    # --- penggunaan lahan
    "PENGGUNAANTANAH_AR_10K": (G_GUNA, "Penggunaan Tanah (Skala 1:10.000)", {"t": "cat", "f": "namobj", "land": True}),
    "PERMUKIMAN_AR_25K": (G_GUNA, "Area Permukiman (Skala 1:25.000)", {"t": "one", "c": "#ff8a65"}),
    "SAWAH_AR_25K": (G_GUNA, "Sawah", {"t": "cat", "f": "REMARK", "c": {"Sawah": "#aeea00", "Sawah Tadah Hujan": "#d4e157"}}),
    "LADANG_AR_25K": (G_GUNA, "Ladang/Tegalan", {"t": "one", "c": "#e6d96b"}),
    "PERKEBUNAN_AR_25K": (G_GUNA, "Perkebunan", {"t": "one", "c": "#7cb342"}),
    "HUTANLAHANTINGGI_AR_25K": (G_GUNA, "Hutan Lahan Tinggi", {"t": "one", "c": "#1b5e20"}),
    "SEMAKBELUKAR_AR_25K": (G_GUNA, "Semak Belukar", {"t": "one", "c": "#c0ca33"}),
    "HERBADANRUMPUT_AR_25K": (G_GUNA, "Herba dan Rumput", {"t": "one", "c": "#c5e1a5"}),
    # --- transportasi & utilitas
    "JALAN_LN_25K": (G_INFRA, "Jaringan Jalan", {"t": "cat", "f": "REMARK", "c": {"Jalan Nasional": ("#d32f2f", 4), "Jalan Lokal": ("#f57c00", 3), "Jalan Lingkungan": ("#fbc02d", 2.4), "Jalan Lain": ("#ffffff", 1.6), "Jalan Setapak": ("#b0bec5", 1.2, "3 3")}}),
    "JEMBATAN_PT_25K": (G_INFRA, "Jembatan", {"t": "one", "c": "#8d6e63", "r": 5}),
    "TONGGAKKM_PT_25K": (G_INFRA, "Tonggak Kilometer Jalan", {"t": "one", "c": "#90a4ae", "r": 5}),
    "JARINGANLISTRIK_LN_SATUPETA": (G_INFRA, "Jaringan Listrik SUTT 70 kV", {"t": "one", "c": "#ff1744", "w": 3, "dash": "10 4"}),
    "KABELLISTRIK_LN_25K": (G_INFRA, "Kabel Listrik", {"t": "one", "c": "#ff9100", "w": 3}),
    "RUANGUDARA_AR_50K": (G_INFRA, "Ruang Udara (Navigasi Penerbangan)", {"t": "cat", "f": "namobj", "auto": True}),
    # --- sarana & lingkungan terbangun
    "SARANAFASILITAS_PT_RBI_OSM": (G_SARANA, "Sarana & Fasilitas Umum (RBI/OSM)", {"t": "cat", "f": "KATEGORI", "auto": True}),
    "PERUMAHAN_PT_25K": (G_SARANA, "Titik Perumahan/Bangunan", {"t": "one", "c": "#ff7043", "r": 3}),
    "PEMERINTAHAN_PT_25K": (G_SARANA, "Fasilitas Pemerintahan", {"t": "cat", "f": "REMARK", "auto": True, "r": 6}),
    "PENDIDIKAN_PT_25K": (G_SARANA, "Fasilitas Pendidikan", {"t": "one", "c": "#42a5f5", "r": 6}),
    "RUMAHSAKIT_PT_25K": (G_SARANA, "Rumah Sakit/Fasilitas Kesehatan", {"t": "one", "c": "#ff1744", "r": 7}),
    "SARANAIBADAH_PT_25K": (G_SARANA, "Sarana Ibadah", {"t": "one", "c": "#00e676", "r": 5}),
    "NIAGA_PT_25K": (G_SARANA, "Fasilitas Niaga/Perdagangan", {"t": "one", "c": "#ffc400", "r": 6}),
    "MAKAM_PT_25K": (G_SARANA, "Pemakaman", {"t": "cat", "f": "REMARK", "c": {"Pemakaman Umum": "#b0bec5", "Pemakaman Bukan Umum": "#78909c"}, "r": 4}),
    # --- kawasan hutan, pertanahan, pertambangan
    "KAWASANHUTAN_AR_SATUPETA": (G_KAWASAN, "Kawasan Hutan (Penetapan KLHK)", {"t": "cat", "f": "nkws", "auto": True}),
    "PELEPASANKAWASANHUTAN_AR_SATUPETA": (G_KAWASAN, "Pelepasan Kawasan Hutan", {"t": "one", "c": "#ffb300"}),
    "PIPPIB_AR_250K": (G_KAWASAN, "Peta Indikatif Penundaan Pemberian Izin Baru (PIPPIB)", {"t": "one", "c": "#8e24aa"}),
    "PPTPKH_AR_SATUPETA": (G_KAWASAN, "Penyelesaian Penguasaan Tanah dalam Kawasan Hutan (PPTPKH)", {"t": "cat", "f": "kriteria", "auto": True}),
    "PITTI_BATASDAERAH_TR_KH_AR": (G_KAWASAN, "PITTI: Kesesuaian Tata Ruang & Kawasan Hutan", {"t": "cat", "f": "tipologi", "c": {"Tidak Bermasalah": "#43a047", "Indikasi Bermasalah": "#e53935", "Lokus Terdapat di Badan Air": "#29b6f6"}, "nostroke": True}),
    "PITTI_HAKATASTANAH_AR": (G_KAWASAN, "PITTI: Hak Atas Tanah", {"t": "cat", "f": "tipologi", "c": {"Tidak Bermasalah": "#43a047", "Indikasi Bermasalah": "#e53935", "Lokus Terdapat di Badan Air": "#29b6f6"}, "nostroke": True}),
    "PITTI_HGU_SAWIT_AR": (G_KAWASAN, "PITTI: HGU Sawit", {"t": "one", "c": "#6d4c41"}),
    "PITTI_PERTAMBANGAN_AR": (G_KAWASAN, "PITTI: Pertambangan", {"t": "one", "c": "#7e57c2"}),
    "WIUP_AR_SATUPETA": (G_KAWASAN, "Wilayah Izin Usaha Pertambangan (WIUP)", {"t": "cat", "f": "commdt", "auto": True}),
    "WKMIGAS_AR_SATUPETA": (G_KAWASAN, "Wilayah Kerja Minyak dan Gas Bumi", {"t": "one", "c": "#ff6d00"}),
}

# --- kolom yang tidak ditampilkan pada popup
SKIP = {"metadata", "srs_id", "fcode", "shape_leng", "shape_area", "shape_le_1", "shape_le_2",
        "objectid_1", "objectid", "orig_fid", "ruleid", "lcode", "spatial_re", "fid_", "ptnid",
        "ptnobjname", "ptndate", "ptnremarks", "ig25k_peng", "rule_id", "ruleid_ksp"}

ALIAS = {
    "NAMOBJ": "Nama Objek", "NAMA": "Klasifikasi", "KELAS": "Kelas", "KODE": "Kode",
    "ARAHAN": "Arahan", "LUAS_HA": "Luas (Ha)", "WADMKD": "Desa/Kelurahan", "WADMKC": "Kecamatan",
    "WADMKK": "Kabupaten", "WADMPR": "Provinsi", "REMARK": "Keterangan", "DESA": "Desa",
    "KEC": "Kecamatan", "PEND23": "Penduduk 2023", "PEND24": "Penduduk 2024", "PEND25": "Penduduk 2025",
    "LK25": "Laki-laki 2025", "PR25": "Perempuan 2025", "SEXRATIO": "Rasio Jenis Kelamin",
    "KPDT_BPS": "Kepadatan BPS (jiwa/km²)", "KPDT_SPA": "Kepadatan Spasial (jiwa/km²)",
    "KPDT_NET": "Kepadatan Neto (jiwa/ha)", "KLS_DESA": "Klasifikasi Desa", "IDM25": "Status IDM 2025",
    "KLS_BPS20": "Perkotaan/Perdesaan (BPS 2020)", "ORDE": "Orde", "KATEGORI": "Kategori",
    "BOBOT": "Bobot", "SUMBER": "Sumber", "TIPOLOGI": "Tipologi", "JIWA": "Jumlah Jiwa",
    "KPDT_HA": "Kepadatan (jiwa/ha)", "KET": "Keterangan", "LUASWH": "Luas Wilayah (km²)",
    "GiZScore": "Gi* Z-Score", "GiPValue": "Gi* P-Value", "ELEVAS": "Elevasi (m)", "VALKNT": "Nilai Kontur (m)",
}


def pretty(name):
    if name in ALIAS:
        return ALIAS[name]
    return re.sub(r"\s+", " ", name.replace("_", " ")).strip().capitalize()


# ------------------------------------------------------------------ utilitas
def r5(v):
    return round(v, 5)


def round_coords(c):
    if isinstance(c[0], (int, float)):
        return [r5(c[0]), r5(c[1])]
    return [round_coords(x) for x in c]


def clean(v):
    if isinstance(v, bytes):
        v = v.decode("utf-8", "replace")
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return None
        return round(v, 3) if v != int(v) else int(v)
    if isinstance(v, str):
        v = v.strip()
        return v if v else None
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return v


def fmt_num(x):
    s = f"{x:,.1f}" if abs(x) < 100 else f"{x:,.0f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def contrast_shade(hexcol, f=0.6):
    h = hexcol.lstrip("#")
    r, g, b = [int(h[i:i + 2], 16) for i in (0, 2, 4)]
    return "#%02x%02x%02x" % (int(r * f), int(g * f), int(b * f))


def read_layer(shp_path):
    rd = shapefile.Reader(shp_path, encoding="utf-8", encodingErrors="replace")
    prj = shp_path[:-4] + ".prj"
    crs = CRS.from_wkt(open(prj).read()) if os.path.exists(prj) else CRS.from_epsg(4326)
    tf = None if crs.is_geographic else Transformer.from_crs(crs, 4326, always_xy=True)
    fields = [f[0] for f in rd.fields[1:]]
    return rd, fields, tf


def to_wgs(geom, tf):
    if tf is None:
        return geom
    from shapely.ops import transform
    return transform(tf.transform, geom)


def prune(g, min_area):
    """Buang bagian/lubang poligon yang sangat kecil (artefak konversi raster-ke-vektor)."""
    from shapely.geometry import Polygon, MultiPolygon
    if g.geom_type not in ("Polygon", "MultiPolygon"):
        return g
    parts = [g] if g.geom_type == "Polygon" else list(g.geoms)
    out = []
    for p in parts:
        if p.area < min_area:
            continue
        holes = [r for r in p.interiors if Polygon(r).area >= min_area]
        out.append(Polygon(p.exterior, holes))
    if not out:
        return g
    return out[0] if len(out) == 1 else MultiPolygon(out)


def tolerance(gtype, n):
    if "POINT" in gtype:
        return 0
    return 0.00004 if n > 3000 else 0.00002


def build_vector(key, shp_path, spec):
    group, title, style = spec
    rd, fields, tf = read_layer(shp_path)
    gtype = rd.shapeTypeName.upper()
    kind = "point" if "POINT" in gtype else "line" if "LINE" in gtype else "polygon"
    n = len(rd)
    tol = tolerance(gtype, n)
    feats = []
    raw_geoms = []
    bounds = [180, 90, -180, -90]
    for sr in rd.iterShapeRecords():
        if sr.shape.shapeType == 0:
            continue
        g = force_2d(shape(sr.shape.__geo_interface__))
        g = to_wgs(g, tf)
        if g.is_empty:
            continue
        raw_geoms.append(g)
        if tol:
            g = g.simplify(tol, preserve_topology=True)
        b = g.bounds
        bounds = [min(bounds[0], b[0]), min(bounds[1], b[1]), max(bounds[2], b[2]), max(bounds[3], b[3])]
        gm = mapping(g)
        props = {}
        rec = sr.record.as_dict()
        for k, v in rec.items():
            if k.lower() in SKIP:
                continue
            props[k] = clean(v)
        feats.append({"type": "Feature", "properties": props,
                      "geometry": {"type": gm["type"], "coordinates": round_coords(gm["coordinates"])}})

    # layer terlalu berat -> sederhanakan lebih kuat (tepi raster-ke-vektor bergerigi)
    if tol:
        size = len(json.dumps([f["geometry"] for f in feats], separators=(",", ":")))
        t2 = tol
        while size > MAX_BYTES and t2 < 0.0009:
            t2 *= 2
            for f, g in zip(feats, raw_geoms):
                gm = mapping(prune(g.simplify(t2, preserve_topology=True), (t2 * 3) ** 2))
                f["geometry"] = {"type": gm["type"], "coordinates": round_coords(gm["coordinates"])}
            size = len(json.dumps([f["geometry"] for f in feats], separators=(",", ":")))

    # buang kolom kosong / seragam tidak informatif
    keep = []
    for k in feats[0]["properties"] if feats else []:
        vals = [f["properties"].get(k) for f in feats]
        if all(v in (None, "-", "", 0, "0") for v in vals):
            continue
        keep.append(k)
    for f in feats:
        f["properties"] = {k: f["properties"][k] for k in keep}

    # ---------------------------------------------------------- simbologi
    st = dict(style)
    cls_field = None
    legend = []
    t = st["t"]
    if t == "one":
        legend = [{"label": title, "color": st["c"]}]
    elif t == "outline":
        legend = [{"label": title, "color": st["c"], "outline": True}]
    elif t == "quant":
        vals = sorted(float(f["properties"][st["f"]]) for f in feats if f["properties"].get(st["f"]) is not None)
        nq = min(st["n"], len(set(vals)))
        qs = [vals[int(len(vals) * i / nq)] for i in range(1, nq)]
        edges = [vals[0]] + qs + [vals[-1]]
        colors = st["c"]
        labels = []
        for i in range(nq):
            labels.append(f"{fmt_num(edges[i])} – {fmt_num(edges[i + 1])} {st['unit']}")
        for f in feats:
            v = f["properties"].get(st["f"])
            if v is None:
                f["properties"]["_cls"] = None
                continue
            idx = sum(1 for q in qs if float(v) >= q)
            f["properties"]["_cls"] = labels[idx]
        cmap = {labels[i]: colors[i] for i in range(nq)}
        st["c"] = cmap
        legend = [{"label": l, "color": cmap[l]} for l in labels]
        cls_field = "_cls"
        st["t"] = "cat"
    elif t == "cat":
        f_spec = st["f"]
        labels_map = st.get("labels", {})
        for f in feats:
            p = f["properties"]
            if "{" in f_spec:
                try:
                    val = f_spec.format(**{k: ("" if v is None else v) for k, v in p.items()})
                except KeyError:
                    val = None
            else:
                val = p.get(f_spec)
            if val is not None and not isinstance(val, str):
                val = str(val)
            if val in labels_map:
                val = labels_map[val]
            p["_cls"] = val
        cls_field = "_cls"
        counts = collections.Counter(f["properties"]["_cls"] for f in feats)
        if st.get("c"):
            cmap = {labels_map.get(k, k): v for k, v in st["c"].items()}
            order = [k for k in cmap if counts.get(k)]
            for v in counts:
                if v is not None and v not in cmap:
                    cmap[v] = "#9e9e9e"
                    order.append(v)
        else:
            order = [v for v, _ in counts.most_common() if v is not None]
            if st.get("land"):
                cmap = {v: land_color(v) for v in order}
            else:
                cmap = {v: QUAL[i % len(QUAL)] for i, v in enumerate(order)}
        if None in counts:
            order.append("Tidak ada data")
            for f in feats:
                if f["properties"]["_cls"] is None:
                    f["properties"]["_cls"] = "Tidak ada data"
            cmap["Tidak ada data"] = "#9e9e9e"
        for v in order:
            c = cmap[v]
            entry = {"label": v, "color": c if isinstance(c, str) else c[0]}
            if isinstance(c, tuple):
                entry["w"] = c[1]
                if len(c) > 2:
                    entry["dash"] = c[2]
            legend.append(entry)
        st["c"] = {k: (v if isinstance(v, str) else list(v)) for k, v in cmap.items()}

    st["field"] = cls_field
    # kolom untuk popup + alias
    popup_fields = [k for k in keep]
    if cls_field:
        for f in feats:
            pass
    aliases = {k: pretty(k) for k in popup_fields}
    label_field = st.get("label")

    os.makedirs(OUT, exist_ok=True)
    fn = os.path.join(OUT, key + ".geojson")
    with open(fn, "w", encoding="utf-8") as fh:
        json.dump({"type": "FeatureCollection", "features": feats}, fh, ensure_ascii=False, separators=(",", ":"))
    size = os.path.getsize(fn)
    entry = {
        "id": key, "group": group, "title": title, "kind": kind, "type": "vector",
        "file": f"data/{key}.geojson", "count": len(feats), "size": size,
        "bounds": [[bounds[1], bounds[0]], [bounds[3], bounds[2]]],
        "style": {k: v for k, v in st.items() if k in ("t", "c", "w", "dash", "r", "field", "nostroke")},
        "legend": legend, "fields": popup_fields, "aliases": aliases, "label": label_field,
    }
    return entry


# -------------------------------------------------------------------- raster
def read_tfw(path):
    v = [float(x) for x in open(path).read().split()]
    return v  # A, D, B, E, C, F


def hex2rgb(h):
    h = h.lstrip("#")
    return [int(h[i:i + 2], 16) for i in (0, 2, 4)]


def apply_ramp(norm, stops):
    """norm 0..1 ; stops [(pos,hex),...] -> uint8 RGB array."""
    pos = np.array([s[0] for s in stops], dtype=float)
    cols = np.array([hex2rgb(s[1]) for s in stops], dtype=float)
    out = np.zeros(norm.shape + (3,), dtype=float)
    for ch in range(3):
        out[..., ch] = np.interp(norm, pos, cols[:, ch])
    return out.astype(np.uint8)


def build_raster(key, tif, group, title, mode, epsg=32749):
    img = Image.open(tif)
    a = np.array(img, dtype="float64")
    A, D, B, E, C, F = read_tfw(tif[:-4] + ".tfw")
    h, w = a.shape
    valid = np.isfinite(a) & (np.abs(a) < 1e20)
    # alihkan piksel (x,y UTM) -> lon/lat grid
    ll = Transformer.from_crs(epsg, 4326, always_xy=True)
    corners = [(C, F), (C + A * w, F), (C, F + E * h), (C + A * w, F + E * h)]
    lons, lats = zip(*[ll.transform(x, y) for x, y in corners])
    west, east, south, north = min(lons), max(lons), min(lats), max(lats)
    ow, oh = w, int(round(w * (north - south) / (east - west) * math.cos(math.radians((north + south) / 2))))
    oh = max(oh, 10)
    lon = west + (np.arange(ow) + 0.5) * (east - west) / ow
    lat = north - (np.arange(oh) + 0.5) * (north - south) / oh
    LON, LAT = np.meshgrid(lon, lat)
    inv = Transformer.from_crs(4326, epsg, always_xy=True)
    X, Y = inv.transform(LON, LAT)
    col = np.floor((X - C) / A).astype(int)
    row = np.floor((Y - F) / E).astype(int)
    inside = (col >= 0) & (col < w) & (row >= 0) & (row < h)
    col = np.clip(col, 0, w - 1)
    row = np.clip(row, 0, h - 1)
    vals = a[row, col]
    ok = inside & valid[row, col]
    rgba = np.zeros((oh, ow, 4), dtype=np.uint8)

    if mode == "dem":
        lo, hi = float(np.nanpercentile(a[valid], 0.5)), float(np.nanpercentile(a[valid], 99.5))
        stops = [(0, "#2e7d32"), (0.2, "#8bc34a"), (0.4, "#f5e663"), (0.6, "#d19a3e"), (0.8, "#8d5524"), (1, "#ffffff")]
        rgba[..., :3] = apply_ramp(np.clip((vals - lo) / (hi - lo), 0, 1), stops)
        legend = {"gradient": [[p, c] for p, c in stops], "min": round(lo), "max": round(hi), "unit": "m dpl"}
    elif mode == "slope":
        breaks = [(2, "#1a9641"), (5, "#a6d96a"), (15, "#ffffbf"), (40, "#fdae61"), (1e9, "#d7191c")]
        names = ["0 – 2 % (Datar)", "2 – 5 % (Berombak)", "5 – 15 % (Berbukit)", "15 – 40 % (Curam)", "> 40 % (Sangat Curam)"]
        rgb = np.zeros(vals.shape + (3,), dtype=np.uint8)
        prev = -1e9
        for (b, c) in breaks:
            m = (vals >= prev) & (vals < b)
            rgb[m] = hex2rgb(c)
            prev = b
        rgba[..., :3] = rgb
        legend = {"classes": [{"label": n, "color": c} for n, (b, c) in zip(names, breaks)]}
    else:  # populasi
        pos = ok & (vals > 0)
        hi = float(np.nanpercentile(a[valid & (a > 0)], 99))
        stops = [(0, "#ffffb2"), (0.25, "#fecc5c"), (0.5, "#fd8d3c"), (0.75, "#f03b20"), (1, "#bd0026")]
        rgba[..., :3] = apply_ramp(np.clip(np.sqrt(np.clip(vals, 0, hi) / hi), 0, 1), stops)
        ok = pos
        legend = {"gradient": [[p, c] for p, c in stops], "min": 0, "max": round(hi, 1), "unit": "jiwa/sel 10 m"}
    rgba[..., 3] = np.where(ok, 255, 0)
    fn = os.path.join(OUT, key + ".png")
    Image.fromarray(rgba, "RGBA").save(fn, optimize=True)
    return {
        "id": key, "group": group, "title": title, "kind": "raster", "type": "raster",
        "file": f"data/{key}.png", "count": 1, "size": os.path.getsize(fn),
        "bounds": [[south, west], [north, east]], "legend": legend,
        "style": {"t": "raster"}, "fields": [], "aliases": {}, "label": None,
    }


# ----------------------------------------------------------------------- main
def main():
    work = tempfile.mkdtemp(prefix="rdtr_")
    shp_files = {}
    rasters = {}
    zips = sorted(glob.glob(os.path.join(ROOT, "*.zip")))
    for z in zips:
        d = os.path.join(work, os.path.basename(z)[:-4])
        os.makedirs(d, exist_ok=True)
        with zipfile.ZipFile(z) as zf:
            zf.extractall(d)
        for p in glob.glob(d + "/**/*.shp", recursive=True):
            shp_files[os.path.basename(p)[:-4]] = (p, os.path.basename(z))
        for p in glob.glob(d + "/**/*.tif", recursive=True):
            rasters[os.path.basename(p)[:-4]] = (p, os.path.basename(z))

    manifest = []
    missing = [k for k in shp_files if k not in L]
    if missing:
        print("PERINGATAN: layer tanpa konfigurasi:", missing)
    for key, (p, zname) in sorted(shp_files.items()):
        spec = L.get(key) or ("Lainnya", key, {"t": "one", "c": "#9e9e9e"})
        print("vektor ", key)
        e = build_vector(key, p, spec)
        e["source"] = zname
        manifest.append(e)

    raster_spec = {
        "DEM_KONTUR25K_10M": (G_RASTER, "Digital Elevation Model (DEM) 10 m dari Kontur 1:25.000", "dem"),
        "LERENG_PERSEN_DEM25K_10M": (G_RASTER, "Kemiringan Lereng (%) dari DEM 10 m", "slope"),
        "PENDUDUK_DASIMETRIK_JIWA_PER_SEL10M": (G_RASTER, "Sebaran Penduduk Dasimetrik (Jiwa per Sel 10 m)", "pop"),
    }
    for key, (p, zname) in sorted(rasters.items()):
        g, title, mode = raster_spec[key]
        print("raster ", key)
        e = build_raster(key, p, g, title, mode)
        e["source"] = zname
        manifest.append(e)

    manifest.sort(key=lambda e: (GROUP_ORDER.index(e["group"]) if e["group"] in GROUP_ORDER else 99,
                                 list(L).index(e["id"]) if e["id"] in L else 999))
    with open(os.path.join(OUT, "layers.json"), "w", encoding="utf-8") as fh:
        json.dump({"groups": GROUP_ORDER, "layers": manifest}, fh, ensure_ascii=False, separators=(",", ":"))
    tot = sum(e["size"] for e in manifest)
    print(f"Selesai: {len(manifest)} layer, total {tot / 1e6:.1f} MB")


if __name__ == "__main__":
    sys.exit(main())
