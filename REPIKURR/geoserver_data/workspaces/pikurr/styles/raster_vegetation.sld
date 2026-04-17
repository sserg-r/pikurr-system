<?xml version="1.0" encoding="UTF-8"?><sld:StyledLayerDescriptor xmlns:sld="http://www.opengis.net/sld" xmlns:gml="http://www.opengis.net/gml" xmlns:ogc="http://www.opengis.net/ogc" xmlns="http://www.opengis.net/sld" version="1.0.0">
  <sld:NamedLayer>
    <sld:Name>Default Styler</sld:Name>
    <sld:UserStyle>
      <sld:Name>Default Styler</sld:Name>
      <sld:Title>A raster style</sld:Title>
      <sld:FeatureTypeStyle>
        <sld:Name>name</sld:Name>
        <sld:Rule>
          <sld:RasterSymbolizer>
            <sld:ColorMap>
              <sld:ColorMapEntry color="#ffffff" quantity="0" opacity="1" />
              <sld:ColorMapEntry color="#4e7626" quantity="1" label="деревья"/>
              <sld:ColorMapEntry color="#30b646" quantity="2" label="кусты"/>
              <sld:ColorMapEntry color="#acf189" quantity="3" label="луг закустаренный"/>
              <sld:ColorMapEntry color="#deffcf" quantity="4" label="луг чистый"/>
              <sld:ColorMapEntry color="#f8f5c4" quantity="5" label="прочее"/>
              <sld:ColorMapEntry color="#cba27b" quantity="6" label="пашня"/>
              
            </sld:ColorMap>
            <sld:ContrastEnhancement/>
          </sld:RasterSymbolizer>
        </sld:Rule>
      </sld:FeatureTypeStyle>
    </sld:UserStyle>
  </sld:NamedLayer>
</sld:StyledLayerDescriptor>