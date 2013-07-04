<?xml version="1.0" encoding="ISO-8859-1"?>
<xsl:stylesheet version="1.0"
    xmlns:xsl="http://www.w3.org/1999/XSL/Transform">
<xsl:param name="nant.filename" />
<xsl:param name="nant.version" />
<xsl:param name="nant.project.name" />
<xsl:param name="nant.project.buildfile" />
<xsl:param name="nant.project.basedir" />
<xsl:param name="nant.project.default" />
<xsl:param name="sys.os" />
<xsl:param name="sys.os.platform" />
<xsl:param name="sys.os.version" />
<xsl:param name="sys.clr.version" />

<!--
<msxsl:script language="C#" implements-prefix="nunit2report">
	
	public string TestCaseName(string path) {
	
	string[] a = path.Split('.');

	return(a[a.Length-1]);
	}

</msxsl:script>
-->
<!--
    TO DO
	Corriger les alignement sur error
	Couleur http://nanning.sourceforge.net/junit-report.html
-->


<!--
    format a number in to display its value in percent
    @param value the number to format
-->
<xsl:template name="display-time">
	<xsl:param name="value"/>
	<xsl:value-of select="format-number($value,'0.000')"/>
</xsl:template>

<!--
    format a number in to display its value in percent
    @param value the number to format
-->
<xsl:template name="display-percent">
	<xsl:param name="value"/>
	<xsl:value-of select="format-number($value,'0.00 %')"/>
</xsl:template>

<!--
    transform string like a.b.c to ../../../
    @param path the path to transform into a descending directory path
-->
<xsl:template name="path">
	<xsl:param name="path"/>
	<xsl:if test="contains($path,'.')">
		<xsl:text>../</xsl:text>	
		<xsl:call-template name="path">
			<xsl:with-param name="path"><xsl:value-of select="substring-after($path,'.')"/></xsl:with-param>
		</xsl:call-template>	
	</xsl:if>
	<xsl:if test="not(contains($path,'.')) and not($path = '')">
		<xsl:text>../</xsl:text>	
	</xsl:if>	
</xsl:template>

<!--
	template that will convert a carriage return into a br tag
	@param word the text from which to convert CR to BR tag
-->
<xsl:template name="br-replace">
	<xsl:param name="word"/>
	<xsl:choose>
		<xsl:when test="contains($word,'&#xA;')">
			<xsl:value-of select="substring-before($word,'&#xA;')"/>
			<br/>
			<xsl:call-template name="br-replace">
				<xsl:with-param name="word" select="substring-after($word,'&#xA;')"/>
			</xsl:call-template>
		</xsl:when>
		<xsl:otherwise>
			<xsl:value-of select="$word"/>
		</xsl:otherwise>
	</xsl:choose>
</xsl:template>

<!-- 
		=====================================================================
		classes summary header
		=====================================================================
-->
<xsl:template name="header">
	<xsl:param name="path"/>

<nav class="sub-menu-container">
<div class="container-inner">
	<div class="dataTables_filter">
		<label>Global filter 
			<input type="text" placeholder="filter text" id="filterinput"/>
			<button class="grey-btn" id="submitFilter">Filter</button>
			<button class="grey-btn" id="clearFilter">Clear</button>
		</label>
	</div>
	<h1 class="logo">
      <a href="/">
        <span>K</span>atana
      </a>
    </h1>
	<h1 id=":i18n:UnitTestsResults" class="main-head big">
		Unit Tests Results <xsl:value-of select="$nant.project.name"/>
	</h1>
</div>
</nav>

</xsl:template>

<xsl:template name="summaryHeader">
	<tr>
		<th class="txt-align-left" id=":i18n:Tests">Tests</th>
		<th class="txt-align-left" id=":i18n:Failures">Failures</th>
		<th class="txt-align-left" id=":i18n:Errors">Errors</th>
		<th class="txt-align-left" id=":i18n:SuccessRate" colspan="2">Success Rate</th>
		<th class="txt-align-left" id=":i18n:Time" nowrap="nowrap">Time(s)</th>
	</tr>
</xsl:template>

<!-- 
		=====================================================================
		package summary header
		=====================================================================
-->
<xsl:template name="packageSummaryHeader">
	<tr class="TableHeader" valign="top">
		<td width="75%" colspan="3"><b id=":i18n:Name">Name</b></td>
		<td width="5%"><b id=":i18n:Tests">Tests</b></td>
		<td width="5%"><b id=":i18n:Errors">Errors</b></td>
		<td width="5%"><b id=":i18n:Failures">Failures</b></td>
		<td width="10%" nowrap="nowrap"><b id=":i18n:Time">Time(s)</b></td>
	</tr>
</xsl:template>


<!-- 
		=====================================================================
		classes summary header
		=====================================================================
-->
<xsl:template name="classesSummaryHeader">
	<tr>
		<th class="txt-align-left" id=":i18n:Name" colspan="2">Name</th>
		<th id=":i18n:Status">Status</th>
		<th id=":i18n:Time" >Time(s)</th>
	</tr>
</xsl:template>

<!-- 
		=====================================================================
		Write the summary report
		It creates a table with computed values from the document:
		User | Date | Environment | Tests | Failures | Errors | Rate | Time
		Note : this template must call at the testsuites level
		=====================================================================
-->
	<xsl:template name="summary">
		<h1 class="main-head" id=":i18n:Summary">Summary</h1>
		<xsl:variable name="runCount" select="@total"/>
		<xsl:variable name="failureCount" select="@failures"/>
		<xsl:variable name="ignoreCount" select="@not-run"/>
		<xsl:variable name="total" select="$runCount + $ignoreCount + $failureCount"/>

		<xsl:variable name="timeCount" select="translate(test-suite/@time,',','.')"/>

		<xsl:variable name="successRate" select="$runCount div $total"/>
		
		<table class="table-1 first-child">
		<thead>
			<xsl:call-template name="summaryHeader"/>
		</thead>
		<tbody>
		<tr>
			<xsl:attribute name="class">
    			<xsl:choose>
    			    <xsl:when test="$failureCount &gt; 0">Failure</xsl:when>
    				<xsl:when test="$ignoreCount &gt; 0">Error</xsl:when>
    				<xsl:otherwise>Pass</xsl:otherwise>
    			</xsl:choose>			
			</xsl:attribute>		
			<td class="txt-align-left"><xsl:value-of select="$runCount"/></td>
			<td class="txt-align-left"><xsl:value-of select="$failureCount"/></td>
			<td class="txt-align-left"><xsl:value-of select="$ignoreCount"/></td>
			<td class="txt-align-left" nowrap="nowrap">
			    <xsl:call-template name="display-percent">
			        <xsl:with-param name="value" select="$successRate"/>
			    </xsl:call-template>
			</td>
			<td class="txt-align-left">
				<xsl:if test="round($runCount * 200 div $total )!=0">
					<span class="covered">
						<xsl:attribute name="style">width:<xsl:value-of select="round($runCount * 200 div $total )"/>px</xsl:attribute>
					</span>
				</xsl:if>
				<xsl:if test="round($ignoreCount * 200 div $total )!=0">
				<span class="ignored">
					<xsl:attribute name="style">width:<xsl:value-of select="round($ignoreCount * 200 div $total )"/>px</xsl:attribute>
				</span>
				</xsl:if>
				<xsl:if test="round($failureCount * 200 div $total )!=0">
					<span class="uncovered">
						<xsl:attribute name="style">width:<xsl:value-of select="round($failureCount * 200 div $total )"/>px</xsl:attribute>
					</span>
				</xsl:if>
			</td>
			<td class="txt-align-left">
			    <xsl:call-template name="display-time">
			        <xsl:with-param name="value" select="$timeCount"/>
			    </xsl:call-template>
			</td>
		</tr>
		</tbody>
		</table>
		<!--
			<span id=":i18n:Note">Note</span>: <i id=":i18n:failures">failures</i>&#160;<span id=":i18n:anticipated">are anticipated and checked for with assertions while</span>&#160;<i id=":i18n:errors">errors</i>&#160;<span id=":i18n:unanticipated">are unanticipated.</span>
		-->
	</xsl:template>

<!-- 
		=====================================================================
		testcase report
		=====================================================================
-->
<xsl:template match="test-case">
	
	<xsl:param name="open.description"/>

	<xsl:variable name="Mname" select="concat('M:',./@name)" />

   <xsl:variable name="result">
			<xsl:choose>
				<xsl:when test="./failure"><span id=":i18n:Failure">Failure</span></xsl:when>
				<xsl:when test="./error"><span id=":i18n:Error">Error</span></xsl:when>
				<xsl:when test="@executed='False'"><span id=":i18n:Ignored">Ignored</span></xsl:when>
				<xsl:otherwise><span id=":i18n:Pass">Pass</span></xsl:otherwise>
			</xsl:choose>
   </xsl:variable>

   <xsl:variable name="newid" select="generate-id(@name)" />
	<tr>
		<td class="txt-align-left">
			
			<!-- If failure, add click on the test method name and color red -->
			<xsl:choose>
				<xsl:when test="$result = 'Failure' or $result = 'Error'">&#160;
					<a title="Show/Hide message error">
					<xsl:attribute name="href">javascript:Toggle('<xsl:value-of select="$newid"/>')</xsl:attribute>
					<xsl:attribute name="class">error case-names link-1</xsl:attribute>
					<xsl:value-of select="./@name"/>
					</a>
				</xsl:when>
				<xsl:when test="$result = 'Ignored'">&#160;<a title="Show/Hide message error">
					<xsl:attribute name="href">javascript:Toggle('<xsl:value-of select="$newid"/>')</xsl:attribute>
					<xsl:attribute name="class">case-names ignored link-1</xsl:attribute>
					<xsl:value-of select="./@name"/>
					</a>
				</xsl:when>
				<xsl:otherwise>
					<xsl:attribute name="class">method txt-align-left case-names</xsl:attribute>&#160;
					<xsl:value-of select="./@name"/>
				</xsl:otherwise>
			</xsl:choose>
		</td>
		<td>
			<xsl:choose>
				<xsl:when test="$result = 'Pass'">
					<span class="covered" ></span>
				</xsl:when>
				<xsl:when test="$result = 'Ignored'">
					<span class="ignored" ></span>
				</xsl:when>			
				<xsl:when test="$result = 'Failure' or $result = 'Error'">
					<span class="uncovered" ></span>
				</xsl:when>			
			</xsl:choose>
			<!-- The test method description-->
				
		</td>
		<td>
			<xsl:attribute name="class"><xsl:value-of select="$result"/></xsl:attribute>
			<xsl:attribute name="id">:i18n:<xsl:value-of select="$result"/></xsl:attribute><xsl:value-of select="$result"/></td>
		<td>
		    <xsl:call-template name="display-time">
		        <xsl:with-param name="value" select="@time"/>
		    </xsl:call-template>				
		</td>
	</tr>

	<xsl:if test="$result != &quot;Pass&quot;">
	   <tr style="display: block;">
	      <xsl:attribute name="id">
	         <xsl:value-of select="$newid"/>
	      </xsl:attribute>
	      <td class="FailureDetail">
	         <xsl:apply-templates select="./failure"/>
	         <xsl:apply-templates select="./error"/>
			 <xsl:apply-templates select="./reason"/>
         </td>
         


      </tr>
	</xsl:if>
</xsl:template>

<!-- Note : the below template error and failure are the same style
            so just call the same style store in the toolkit template -->
<!-- <xsl:template match="failure">
	<xsl:call-template name="display-failures"/>
</xsl:template>

<xsl:template match="error">
	<xsl:call-template name="display-failures"/>
</xsl:template> -->

<!-- Style for the error and failure in the tescase template -->
<!-- <xsl:template name="display-failures">
	<xsl:choose>
		<xsl:when test="not(@message)">N/A</xsl:when>
		<xsl:otherwise>
			<xsl:value-of select="@message"/>
		</xsl:otherwise>
	</xsl:choose> -->
	<!-- display the stacktrace -->
<!-- 	<code>
		<p/>
		<xsl:call-template name="br-replace">
			<xsl:with-param name="word" select="."/>
		</xsl:call-template>
	</code> -->
	<!-- the later is better but might be problematic for non-21" monitors... -->
	<!--pre><xsl:value-of select="."/></pre-->
<!-- </xsl:template>
 -->

<!-- 
		=====================================================================
		Environtment Info Report
		=====================================================================
-->
<xsl:template name="envinfo">
   <a name="envinfo"></a>
	<h2 id=":i18n:EnvironmentInformation">Environment Information</h2>
	<table border="0" cellpadding="5" cellspacing="2" width="95%">
	   <tr class="TableHeader">
	      <td id=":i18n:Property">Property</td>
	      <td id=":i18n:Value">Value</td>
	   </tr>
	   <tr>
	      <td id=":i18n:NAntLocation">NAnt Location</td>
	      <td><xsl:value-of select="$nant.filename"/></td>
	   </tr>
	   <tr>
	      <td id=":i18n:NAntVersion">NAnt Version</td>
	      <td><xsl:value-of select="$nant.version"/></td>
	   </tr>
	   <tr>
	      <td id=":i18n:Buildfile">Buildfile</td>
	      <td><xsl:value-of select="$nant.project.buildfile"/></td>
	   </tr>
	   <tr>
	      <td id=":i18n:BaseDirectory">Base Directory</td>
	      <td><xsl:value-of select="$nant.project.basedir"/></td>
	   </tr>
	   <tr>
	      <td id=":i18n:OperatingSystem">Operating System</td>
	      <td><xsl:value-of select="$sys.os"/></td>
	   </tr>
	   <tr>
	      <td id=":i18n:NETCLRVersion">.NET CLR Version</td>
	      <td><xsl:value-of select="$sys.clr.version"/></td>
	   </tr>
   </table>	
	<a href="#top" id=":i18n:Backtotop">Back to top</a>
</xsl:template>

<!-- I am sure that all nodes are called -->
<xsl:template match="*">
	<xsl:apply-templates/>
</xsl:template>

</xsl:stylesheet>