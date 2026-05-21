<?xml version="1.0" encoding="UTF-8"?>
<xsl:stylesheet version="1.0"
  xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
  xmlns:s="http://www.sitemaps.org/schemas/sitemap/0.9">
  <xsl:output method="html" encoding="UTF-8"/>

  <xsl:template match="/">
    <html>
      <head>
        <title>SonicCity sitemap</title>
        <meta charset="UTF-8"/>
        <style>
          body{margin:0;padding:18px 22px;background:#fff;color:#111;font:15px/1.55 ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,"Liberation Mono","Courier New",monospace}
          .note{font:16px/1.45 Georgia,"Times New Roman",serif;margin:0 0 10px;color:#111}
          .rule{border:0;border-top:2px solid #111;margin:0 0 14px}
          .tree{white-space:pre-wrap;margin:0}
          .tag{color:#8b008b}
          .attr{color:#c65f00}
          .val{color:#102ad5}
          .text{color:#111}
          a{color:#102ad5;text-decoration:none}
          a:hover{text-decoration:underline}
        </style>
      </head>
      <body>
        <p class="note">This XML file does not appear to have any style information associated with it. The document tree is shown below.</p>
        <hr class="rule"/>
        <pre class="tree"><xsl:choose>
          <xsl:when test="s:urlset">
            <span class="tag">&lt;urlset</span><xsl:text> </xsl:text><span class="attr">xmlns</span><xsl:text>=</xsl:text><span class="val">"http://www.sitemaps.org/schemas/sitemap/0.9"</span><span class="tag">&gt;</span><xsl:text>&#10;</xsl:text>
            <xsl:for-each select="s:urlset/s:url">
              <xsl:text>  </xsl:text><span class="tag">&lt;url&gt;</span><xsl:text>&#10;</xsl:text>
              <xsl:text>    </xsl:text><span class="tag">&lt;loc&gt;</span><a><xsl:attribute name="href"><xsl:value-of select="s:loc"/></xsl:attribute><xsl:value-of select="s:loc"/></a><span class="tag">&lt;/loc&gt;</span><xsl:text>&#10;</xsl:text>
              <xsl:text>    </xsl:text><span class="tag">&lt;lastmod&gt;</span><span class="text"><xsl:value-of select="s:lastmod"/></span><span class="tag">&lt;/lastmod&gt;</span><xsl:text>&#10;</xsl:text>
              <xsl:text>    </xsl:text><span class="tag">&lt;priority&gt;</span><span class="text"><xsl:value-of select="s:priority"/></span><span class="tag">&lt;/priority&gt;</span><xsl:text>&#10;</xsl:text>
              <xsl:text>    </xsl:text><span class="tag">&lt;changefreq&gt;</span><span class="text"><xsl:value-of select="s:changefreq"/></span><span class="tag">&lt;/changefreq&gt;</span><xsl:text>&#10;</xsl:text>
              <xsl:text>  </xsl:text><span class="tag">&lt;/url&gt;</span><xsl:text>&#10;</xsl:text>
            </xsl:for-each>
            <span class="tag">&lt;/urlset&gt;</span><xsl:text>&#10;</xsl:text>
          </xsl:when>
          <xsl:when test="s:sitemapindex">
            <span class="tag">&lt;sitemapindex</span><xsl:text> </xsl:text><span class="attr">xmlns</span><xsl:text>=</xsl:text><span class="val">"http://www.sitemaps.org/schemas/sitemap/0.9"</span><span class="tag">&gt;</span><xsl:text>&#10;</xsl:text>
            <xsl:for-each select="s:sitemapindex/s:sitemap">
              <xsl:text>  </xsl:text><span class="tag">&lt;sitemap&gt;</span><xsl:text>&#10;</xsl:text>
              <xsl:text>    </xsl:text><span class="tag">&lt;loc&gt;</span><a><xsl:attribute name="href"><xsl:value-of select="s:loc"/></xsl:attribute><xsl:value-of select="s:loc"/></a><span class="tag">&lt;/loc&gt;</span><xsl:text>&#10;</xsl:text>
              <xsl:text>    </xsl:text><span class="tag">&lt;lastmod&gt;</span><span class="text"><xsl:value-of select="s:lastmod"/></span><span class="tag">&lt;/lastmod&gt;</span><xsl:text>&#10;</xsl:text>
              <xsl:text>  </xsl:text><span class="tag">&lt;/sitemap&gt;</span><xsl:text>&#10;</xsl:text>
            </xsl:for-each>
            <span class="tag">&lt;/sitemapindex&gt;</span><xsl:text>&#10;</xsl:text>
          </xsl:when>
        </xsl:choose></pre>
      </body>
    </html>
  </xsl:template>
</xsl:stylesheet>
