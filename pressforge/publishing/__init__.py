"""Sistema de publicación: metadatos de post, cola programada y publicadores.

Diseño modular (igual que el resto): un `PublishProvider` por red social. Hoy
solo hay 'manual' (prepara el caption para publicar a mano); YouTube/Instagram/
Facebook/TikTok se enchufan después sin tocar la cola ni el scheduler.
"""
