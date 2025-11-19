"""
UTD Admissions Scraper
Scrapes admissions information, requirements, deadlines, and financial information from UTD admissions pages.
"""

import asyncio
import logging
import re
from typing import List, Optional, Tuple, Dict
from urllib.parse import urljoin

from playwright.async_api import Browser, Page, TimeoutError as PlaywrightTimeoutError

from .scraper_service import UTDCatalogScraper

logger = logging.getLogger(__name__)


class UTDAdmissionsScraper(UTDCatalogScraper):
    """Scraper for UTD admissions pages."""
    
    BASE_URL = "https://www.utdallas.edu/admissions/"
    
    def __init__(
        self,
        max_pages: Optional[int] = None,
        rate_limit: float = 1.0,
        max_parallel: int = 3,
        output_dir: str = "./data/admissions"
    ):
        """
        Initialize the scraper.
        
        Args:
            max_pages: Maximum number of pages to scrape (None for all)
            rate_limit: Delay between requests in seconds
            max_parallel: Maximum number of concurrent browser instances
            output_dir: Directory to save scraped data
        """
        # Initialize parent with same parameters
        super().__init__(
            max_pages=max_pages,
            rate_limit=rate_limit,
            max_parallel=max_parallel,
            output_dir=output_dir
        )
    
    def _clean_content_text(self, text: str) -> str:
        """Clean and filter content text to remove navigation elements and noise."""
        if not text:
            return ""
        
        lines = text.split('\n')
        cleaned_lines = []
        
        # Filter out navigation-like content
        navigation_patterns = [
            r'^(skip to|menu|navigation|home|about|contact|search)',
            r'^(facebook|twitter|linkedin|instagram|youtube)',
            r'^©\s*\d{4}',
            r'^the university of texas at dallas\s*>\s*',
            r'^\s*>\s*$',  # Just arrows
        ]
        
        # Filter out very short lines that are likely navigation
        for line in lines:
            line_stripped = line.strip()
            
            # Skip empty lines
            if not line_stripped:
                continue
            
            # Skip lines that are just navigation
            is_navigation = any(re.match(pattern, line_stripped, re.IGNORECASE) 
                              for pattern in navigation_patterns)
            
            # Skip lines that are all caps and very short (likely navigation buttons)
            if len(line_stripped) < 3:
                continue
            
            # Skip lines that are all caps and contain only common navigation words
            if line_stripped.isupper() and len(line_stripped) < 50:
                nav_words = ['apply', 'more', 'info', 'contact', 'faq', 'visit', 'request', 'now', 'here', 'learn']
                # Skip if it's a short all-caps line with navigation words
                if any(word in line_stripped.lower() for word in nav_words) and len(line_stripped.split()) <= 4:
                    # But keep if it's a meaningful header
                    meaningful_headers = ['steps to apply', 'deadlines', 'requirements', 'contact us', 'frequently asked']
                    if not any(header in line_stripped.lower() for header in meaningful_headers):
                        continue
            
            if not is_navigation:
                cleaned_lines.append(line_stripped)
        
        # Join and clean up excessive whitespace
        cleaned_text = '\n'.join(cleaned_lines)
        # Remove excessive blank lines
        cleaned_text = re.sub(r'\n{3,}', '\n\n', cleaned_text)
        
        return cleaned_text.strip()
    
    async def find_admissions_links(self, page: Page) -> List[Tuple[str, str]]:
        """
        Find all relevant admissions page links.
        Overrides parent's find_program_links method for admissions-specific logic.
        
        Returns:
            List of tuples (url, page_title)
        """
        try:
            await page.goto(self.BASE_URL, wait_until="domcontentloaded", timeout=60000)
            # Wait a bit for dynamic content to load
            await page.wait_for_timeout(2000)
        except Exception as e:
            logger.warning(f"Error loading base URL, trying with load state: {e}")
            try:
                await page.goto(self.BASE_URL, wait_until="load", timeout=60000)
            except Exception as e2:
                logger.error(f"Failed to load base URL: {e2}")
                # Return at least the main page
                return [(self.BASE_URL, "Main Admissions")]
        
        await self._rate_limit()
        
        links = []
        seen_urls = {self.BASE_URL}  # Track visited URLs
        
        # Start with main admissions page
        links.append((self.BASE_URL, "Main Admissions"))
        
        # Find links to key admissions sections
        all_links = await page.query_selector_all('a')
        keywords = [
            'undergraduate', 'graduate', 'international', 'transfer',
            'requirements', 'deadline', 'application', 'apply',
            'scholarship', 'financial', 'tuition', 'cost'
        ]
        
        for link in all_links:
            try:
                href = await link.get_attribute('href')
                text = await link.inner_text()
                
                if not href or not text:
                    continue
                
                text_lower = text.lower()
                href_lower = href.lower()
                
                # Check if link is relevant to admissions
                is_relevant = any(keyword in text_lower or keyword in href_lower 
                                 for keyword in keywords)
                
                # Check if it's a UTD admissions URL
                is_utd_admissions = ('utdallas.edu/admissions' in href_lower or 
                                    href_lower.startswith('/admissions'))
                
                if is_relevant and is_utd_admissions:
                    # Convert relative URLs to absolute
                    if href.startswith('/'):
                        full_url = urljoin('https://www.utdallas.edu', href)
                    elif href.startswith('http'):
                        full_url = href
                    else:
                        full_url = urljoin(self.BASE_URL, href)
                    
                    # Normalize URL (remove fragments, trailing slashes)
                    full_url = full_url.split('#')[0].rstrip('/')
                    
                    if full_url not in seen_urls and 'utdallas.edu/admissions' in full_url:
                        seen_urls.add(full_url)
                        links.append((full_url, text.strip()))
            except Exception as e:
                logger.debug(f"Error processing link: {e}")
                continue
        
        # Add known important pages with more specific sub-pages
        # Use correct domains - graduate admissions uses graduate-admissions.utdallas.edu
        important_pages = [
            ("https://www.utdallas.edu/admissions/undergraduate/", "Undergraduate Admissions"),
            ("https://www.utdallas.edu/admissions/graduate/", "Graduate Admissions"),
            ("https://www.utdallas.edu/admissions/international/", "International Admissions"),
            # Graduate-specific detailed pages (using correct domain)
            ("https://graduate-admissions.utdallas.edu/", "Graduate Admissions Main"),
            ("https://graduate-admissions.utdallas.edu/contact-us/", "Graduate Contact"),
            ("https://graduate-admissions.utdallas.edu/apply-to-ut-dallas/deadlines-and-fees/", "Graduate Deadlines and Fees"),
            ("https://graduate-admissions.utdallas.edu/apply-to-ut-dallas/apply/", "Graduate Steps to Apply"),
            ("https://graduate-admissions.utdallas.edu/apply-to-ut-dallas/funding-and-financial-aid/", "Graduate Funding and Financial Aid"),
        ]
        
        for url, title in important_pages:
            if url not in seen_urls:
                seen_urls.add(url)
                links.append((url, title))
        
        # After getting initial links, try to find more detailed links from the graduate page
        try:
            # Look for links that might lead to detailed information
            detailed_link_keywords = [
                'steps', 'apply', 'deadline', 'fee', 'requirement', 
                'contact', 'faq', 'program', 'degree', 'application'
            ]
            
            all_links_on_page = await page.query_selector_all('a')
            for link in all_links_on_page:
                try:
                    href = await link.get_attribute('href')
                    text = await link.inner_text()
                    
                    if not href:
                        continue
                    
                    href_lower = href.lower()
                    text_lower = (text or '').lower()
                    
                    # Check if it's a detailed admissions page
                    # Accept both www.utdallas.edu/admissions and graduate-admissions.utdallas.edu
                    is_detailed = (
                        (('admissions' in href_lower or '/admissions/' in href_lower or 'graduate-admissions.utdallas.edu' in href_lower)) and
                        any(keyword in href_lower or keyword in text_lower 
                            for keyword in detailed_link_keywords) and
                        href_lower not in [l[0].lower() for l in links]
                    )
                    
                    if is_detailed:
                        if href.startswith('/'):
                            # Check if it's a graduate-admissions link
                            if 'graduate' in href_lower or 'graduate-admissions' in href_lower:
                                full_url = urljoin('https://graduate-admissions.utdallas.edu', href)
                            else:
                                full_url = urljoin('https://www.utdallas.edu', href)
                        elif href.startswith('http') and ('utdallas.edu' in href or 'graduate-admissions.utdallas.edu' in href):
                            full_url = href
                        else:
                            continue
                        
                        full_url = full_url.split('#')[0].rstrip('/')
                        
                        # Accept both domains
                        if full_url not in seen_urls and ('utdallas.edu/admissions' in full_url or 'graduate-admissions.utdallas.edu' in full_url):
                            seen_urls.add(full_url)
                            link_title = text.strip() if text else href.split('/')[-1].replace('-', ' ').title()
                            links.append((full_url, link_title))
                except Exception as e:
                    logger.debug(f"Error processing detailed link: {e}")
                    continue
        except Exception as e:
            logger.warning(f"Error finding detailed links: {e}")
        
        logger.info(f"Found {len(links)} admissions-related links")
        return links
    
    async def scrape_admissions_page(self, page: Page, url: str, follow_links: bool = False, visited_urls: Optional[set] = None, max_link_depth: int = 1) -> Dict[str, Optional[str]]:
        """
        Scrape an admissions page to extract relevant information.
        
        Args:
            page: Playwright page object
            url: URL to scrape
            follow_links: Whether to follow financial-related links from this page
            visited_urls: Set of already visited URLs to prevent loops
            max_link_depth: Maximum depth to follow links (0 = don't follow)
        
        Returns:
            Dictionary with keys: content, requirements, deadlines, contact_info, financial_info
        """
        if visited_urls is None:
            visited_urls = set()
        
        if url in visited_urls:
            logger.debug(f"Skipping already visited URL: {url}")
            return {
                'content': None,
                'requirements': None,
                'deadlines': None,
                'contact_info': None,
                'financial_info': None
            }
        
        visited_urls.add(url)
        
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            # Wait a bit for dynamic content
            await page.wait_for_timeout(2000)
            await self._rate_limit()
            
            # Check if this is an error page (page doesn't exist)
            page_text = await page.inner_text('body')
            if ("The page you requested does not exist" in page_text or 
                "404" in page_text.lower() or 
                "page not found" in page_text.lower()):
                logger.warning(f"Page does not exist (404): {url}")
                return {
                    'content': None,
                    'requirements': None,
                    'deadlines': None,
                    'contact_info': None,
                    'financial_info': None
                }
            
            # Verify page loaded correctly by checking title/content
            page_title = await page.title()
            if not page_title or len(page_title) < 5:
                logger.warning(f"Page appears invalid (no title): {url}")
                return {
                    'content': None,
                    'requirements': None,
                    'deadlines': None,
                    'contact_info': None,
                    'financial_info': None
                }
            
            # Extract main content with better filtering
            # First, try to find the main content area
            main_content = await page.query_selector('main, .main-content, #content, .content, article, [role="main"]')
            
            if main_content:
                # Remove navigation and other non-content elements from main
                await page.evaluate("""
                    (mainEl) => {
                        if (!mainEl) return;
                        const toRemove = mainEl.querySelectorAll('nav, header, footer, .skip-link, .social-share, .breadcrumb, .navigation, .menu, .sidebar, .related-links, script, style, iframe');
                        toRemove.forEach(el => el.remove());
                    }
                """, main_content)
                content_text = await main_content.inner_text()
            else:
                # Fallback: clean body content more aggressively
                await page.evaluate("""
                    () => {
                        const toRemove = document.querySelectorAll('script, style, nav, header, footer, .skip-link, .social-share, .breadcrumb, .navigation, .menu, .sidebar, .related-links, .site-header, .site-footer, .utility-nav, .main-nav, iframe');
                        toRemove.forEach(el => el.remove());
                    }
                """)
                body = await page.query_selector('body')
                content_text = await body.inner_text() if body else await page.inner_text('body')
            
            # Clean up the text - remove excessive whitespace and filter out navigation-like content
            content_text = self._clean_content_text(content_text)
            
            # Skip if content indicates error page
            if "The page you requested does not exist" in content_text or len(content_text) < 50:
                logger.warning(f"Skipping invalid page content: {url}")
                return {
                    'content': None,
                    'requirements': None,
                    'deadlines': None,
                    'contact_info': None,
                    'financial_info': None
                }
            
            # Extract structured information
            requirements = self._extract_requirements(content_text)
            deadlines = self._extract_deadlines(content_text)
            contact_info = self._extract_contact_info(content_text, url)
            financial_info = self._extract_financial_info(content_text)
            
            # If follow_links is enabled and we haven't exceeded max depth, follow financial-related links
            # Note: We'll handle link following in the caller since we need browser context
            linked_financial_info = []
            
            # Combine financial info from main page and linked pages
            if linked_financial_info:
                if financial_info:
                    financial_info = f"{financial_info}\n\n---\n\n" + "\n\n---\n\n".join(linked_financial_info)
                else:
                    financial_info = "\n\n---\n\n".join(linked_financial_info)
            
            return {
                'content': content_text,
                'requirements': requirements,
                'deadlines': deadlines,
                'contact_info': contact_info,
                'financial_info': financial_info
            }
            
        except PlaywrightTimeoutError:
            logger.error(f"Timeout loading page: {url}")
            return {
                'content': None,
                'requirements': None,
                'deadlines': None,
                'contact_info': None,
                'financial_info': None
            }
        except Exception as e:
            logger.error(f"Error scraping admissions page {url}: {e}")
            return {
                'content': None,
                'requirements': None,
                'deadlines': None,
                'contact_info': None,
                'financial_info': None
            }
    
    async def _find_financial_links(self, page: Page, current_url: str) -> List[Tuple[str, str]]:
        """Find links on the page that are related to financial information."""
        financial_link_keywords = [
            'cost', 'tuition', 'fee', 'financial aid', 'scholarship', 
            'funding', 'deadline', 'deadlines & fees', 'deadlines and fees',
            'affordability', 'price', 'expense'
        ]
        
        links = []
        all_links = await page.query_selector_all('a')
        
        for link in all_links:
            try:
                href = await link.get_attribute('href')
                text = await link.inner_text()
                
                if not href:
                    continue
                
                href_lower = href.lower()
                text_lower = (text or '').lower()
                
                # Check if link is financial-related
                is_financial = any(keyword in text_lower or keyword in href_lower 
                                 for keyword in financial_link_keywords)
                
                if is_financial:
                    # Convert to absolute URL
                    if href.startswith('/'):
                        if 'graduate-admissions' in current_url:
                            full_url = urljoin('https://graduate-admissions.utdallas.edu', href)
                        else:
                            full_url = urljoin('https://www.utdallas.edu', href)
                    elif href.startswith('http'):
                        full_url = href
                    else:
                        full_url = urljoin(current_url, href)
                    
                    full_url = full_url.split('#')[0].rstrip('/')
                    
                    # Only include UTD admissions URLs
                    if ('utdallas.edu' in full_url or 'graduate-admissions.utdallas.edu' in full_url):
                        link_title = text.strip() if text else href.split('/')[-1].replace('-', ' ').title()
                        links.append((full_url, link_title))
            except Exception as e:
                logger.debug(f"Error processing financial link: {e}")
                continue
        
        return links
    
    def _extract_requirements(self, text: str) -> Optional[str]:
        """Extract admission requirements from text."""
        if not text:
            return None
        
        # Look for sections with requirements keywords
        lines = text.split('\n')
        requirements_sections = []
        current_section = []
        in_requirements_section = False
        
        requirement_keywords = [
            'requirement', 'required', 'gpa', 'grade point average', 'grades',
            'sat', 'act', 'gre', 'gmat', 'toefl', 'ielts', 'english proficiency',
            'transcript', 'application', 'prerequisite', 'minimum', 'bachelor',
            'degree', 'coursework', 'recommendation', 'letter of recommendation',
            'statement of purpose', 'resume', 'cv', 'portfolio', 'essay'
        ]
        
        # Also look for numbered lists or bullet points that might indicate requirements
        list_indicators = [r'^\d+\.', r'^[-•*]', r'^[a-z]\)']
        
        for i, line in enumerate(lines):
            line_stripped = line.strip()
            line_lower = line_stripped.lower()
            
            # Check if this line contains requirement keywords
            has_keyword = any(keyword in line_lower for keyword in requirement_keywords)
            
            # Check if this looks like a requirements section header
            is_header = (
                (line_lower.isupper() and any(keyword in line_lower for keyword in ['requirement', 'admission', 'application', 'apply'])) or
                (any(keyword in line_lower for keyword in ['requirement', 'admission requirements', 'application requirements', 'how to apply']) and
                 len(line_lower) < 100)
            )
            
            # Check if it's a list item (might be a requirement)
            is_list_item = any(re.match(pattern, line_stripped) for pattern in list_indicators)
            
            if has_keyword or is_header or (is_list_item and in_requirements_section):
                in_requirements_section = True
                if current_section and len(current_section) > 2:
                    requirements_sections.append('\n'.join(current_section))
                current_section = [line_stripped]
            elif in_requirements_section:
                if line_stripped:
                    # Continue section if it's content or another list item
                    if is_list_item or len(line_stripped) > 10:
                        current_section.append(line_stripped)
                    else:
                        # Might be end of section
                        if len(current_section) > 2:
                            requirements_sections.append('\n'.join(current_section))
                        current_section = []
                        in_requirements_section = False
                elif len(current_section) > 2:  # End section on empty line if we have content
                    requirements_sections.append('\n'.join(current_section))
                    current_section = []
                    in_requirements_section = False
                else:
                    current_section = []
                    in_requirements_section = False
        
        # Add last section if exists
        if current_section and len(current_section) > 2:
            requirements_sections.append('\n'.join(current_section))
        
        if requirements_sections:
            # Filter and join sections - be more lenient with length
            filtered = [s for s in requirements_sections if len(s) > 30]  # Lower threshold
            if filtered:
                return '\n\n---\n\n'.join(filtered[:5])  # Top 5 sections for more detail
        return None
    
    def _extract_deadlines(self, text: str) -> Optional[str]:
        """Extract application deadlines from text."""
        if not text:
            return None
        
        # Look for deadline sections
        lines = text.split('\n')
        deadline_sections = []
        current_section = []
        in_deadline_section = False
        
        deadline_keywords = ['deadline', 'due date', 'application deadline', 'apply by', 'deadlines & fees', 'deadlines and fees']
        semester_keywords = ['fall', 'spring', 'summer', 'winter']
        # More comprehensive date patterns
        date_pattern = r'\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{1,2}\s+(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{4}|(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2},?\s+\d{4}'
        
        for i, line in enumerate(lines):
            line_stripped = line.strip()
            line_lower = line_stripped.lower()
            
            # Check if this line contains deadline keywords or dates
            has_deadline_keyword = any(keyword in line_lower for keyword in deadline_keywords)
            has_semester = any(sem in line_lower for sem in semester_keywords)
            has_date = bool(re.search(date_pattern, line_stripped, re.IGNORECASE))
            
            # Check for list items that might be deadlines
            is_list_item = bool(re.match(r'^\d+\.|^[-•*]', line_stripped))
            
            if has_deadline_keyword or (has_semester and has_date) or (is_list_item and (has_date or has_semester)):
                in_deadline_section = True
                if current_section and len(current_section) > 1:
                    deadline_sections.append('\n'.join(current_section))
                current_section = [line_stripped]
            elif in_deadline_section:
                if line_stripped:
                    # Continue if it's a list item, has a date, or is substantial content
                    if is_list_item or has_date or has_semester or len(line_stripped) > 15:
                        current_section.append(line_stripped)
                    elif len(current_section) > 1:
                        deadline_sections.append('\n'.join(current_section))
                        current_section = []
                        in_deadline_section = False
                elif len(current_section) > 1:
                    deadline_sections.append('\n'.join(current_section))
                    current_section = []
                    in_deadline_section = False
                else:
                    current_section = []
                    in_deadline_section = False
        
        # Add last section if exists
        if current_section and len(current_section) > 1:
            deadline_sections.append('\n'.join(current_section))
        
        if deadline_sections:
            filtered = [s for s in deadline_sections if len(s) > 15]  # Lower threshold
            if filtered:
                return '\n\n---\n\n'.join(filtered[:5])  # More sections
        return None
    
    def _extract_contact_info(self, text: str, url: str) -> Optional[str]:
        """Extract contact information from text."""
        if not text:
            return None
        
        # Search the full text for contact information
        # Contact info can be anywhere in the content
        search_text = text
        
        # Extract phone numbers - improved pattern to catch various formats
        # Pattern 1: Phone: 972-883-2270 or Phone	972-883-2270 (with tab)
        phone_pattern1 = r'(?:phone|call|tel|contact)[\s\t:]*(\d{3}[-.\s]?\d{3}[-.\s]?\d{4})'
        phone_matches = re.finditer(phone_pattern1, search_text, re.IGNORECASE)
        phones = []
        for match in phone_matches:
            phone_str = match.group(1)
            # Format consistently
            phone_clean = re.sub(r'[-.\s]', '-', phone_str)
            phones.append(phone_clean)
        
        # Pattern 2: Standalone phone patterns (UTD format: 972-883-xxxx or 972.883.xxxx)
        # But exclude if already captured
        standalone_phone = r'\b(?:972|214|469)[-.\s]?\d{3}[-.\s]?\d{4}\b|\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b'
        standalone_matches = re.finditer(standalone_phone, search_text)
        for match in standalone_matches:
            phone_str = match.group(0)
            phone_clean = re.sub(r'[-.\s]', '-', phone_str)
            # Only add if not already captured and not part of a fax number
            if phone_clean not in phones and 'fax' not in search_text[max(0, match.start()-20):match.start()].lower():
                phones.append(phone_clean)
        
        # Extract email addresses - filter out common false positives
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        all_emails = re.findall(email_pattern, search_text)
        # Filter out common non-contact emails, prioritize utdallas.edu emails
        emails = [e for e in all_emails if not any(x in e.lower() for x in ['example', 'test', 'noreply', 'donotreply'])]
        # Prioritize utdallas.edu emails
        utd_emails = [e for e in emails if 'utdallas.edu' in e.lower()]
        emails = utd_emails if utd_emails else emails
        
        # Extract addresses - improved pattern, must include street type and location
        address_pattern = r'\d+\s+[\w\s]+(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Drive|Dr|Lane|Ln|Way|Circle|Cir)[\s\S]{0,100}(?:Richardson|Texas|TX|Dallas|\d{5})'
        addresses = re.findall(address_pattern, search_text, re.IGNORECASE)
        # Filter out false positives (like years, distances)
        addresses = [a for a in addresses if not re.match(r'^\d{4}', a.strip()) and 'mile' not in a.lower()]
        
        # Extract office hours if present
        hours_pattern = r'(?:office hours|hours)[\s:]*([^\n]{10,100})'
        hours_match = re.search(hours_pattern, search_text, re.IGNORECASE)
        office_hours = hours_match.group(1).strip() if hours_match else None
        
        # Extract fax if present
        fax_pattern = r'fax[\s:]*(\d{3}[-.\s]?\d{3}[-.\s]?\d{4})'
        fax_match = re.search(fax_pattern, search_text, re.IGNORECASE)
        fax = fax_match.group(1) if fax_match else None
        
        # Extract room number if present (must be after "Room" label, not "Office Hours")
        room_pattern = r'room[\s#:]+number[\s:]*([A-Z0-9\s.-]{3,30})|room[\s#:]+([A-Z0-9\s.-]{2,20})(?:\s|$)(?!hours)'
        room_match = re.search(room_pattern, search_text, re.IGNORECASE)
        room = None
        if room_match:
            room = room_match.group(1) or room_match.group(2)
            room = room.strip() if room else None
            # Filter out false positives
            if room and 'hours' not in room.lower() and len(room) < 50:
                pass
            else:
                room = None
        
        contact_parts = []
        if phones:
            # Deduplicate and limit
            unique_phones = list(dict.fromkeys(phones))[:3]
            contact_parts.append(f"Phone: {', '.join(unique_phones)}")
        if fax:
            contact_parts.append(f"Fax: {fax}")
        if emails:
            unique_emails = list(dict.fromkeys(emails))[:3]
            contact_parts.append(f"Email: {', '.join(unique_emails)}")
        if addresses:
            contact_parts.append(f"Address: {addresses[0]}")
        if room:
            contact_parts.append(f"Room: {room}")
        if office_hours:
            contact_parts.append(f"Office Hours: {office_hours}")
        if url:
            contact_parts.append(f"URL: {url}")
        
        return '\n'.join(contact_parts) if contact_parts else None
    
    def _extract_financial_info(self, text: str) -> Optional[str]:
        """Extract financial information from text - focusing on specific numbers and dollar amounts."""
        if not text:
            return None
        
        # Pattern to find dollar amounts
        dollar_pattern = r'\$[\d,]+(?:\.\d{2})?|\d+[\d,]*\s*(?:dollars?|USD)'
        # Pattern to find percentages
        percent_pattern = r'\d+%'
        
        # Look for specific financial section headers
        financial_section_headers = [
            'application fee', 'application fees', 'tuition', 'costs and tuition',
            'financial aid', 'funding', 'scholarship', 'fee waiver'
        ]
        
        lines = text.split('\n')
        financial_sections = []
        current_section = []
        in_financial_section = False
        section_start_idx = -1
        
        for i, line in enumerate(lines):
            line_stripped = line.strip()
            line_lower = line_stripped.lower()
            
            # Check if this is a financial section header
            is_financial_header = any(
                header in line_lower and 
                (line_lower.isupper() or len(line_lower) < 100 or i == 0 or lines[max(0, i-1)].strip() == '')
                for header in financial_section_headers
            )
            
            # Check if line contains financial keywords and numbers
            has_dollar = bool(re.search(dollar_pattern, line_stripped))
            has_percent = bool(re.search(percent_pattern, line_stripped))
            has_fee_number = bool(re.search(r'\b(?:75|50|100|25|200|500|1000|5000)\b', line_stripped)) and any(
                word in line_lower for word in ['fee', 'cost', 'tuition', 'application', 'waiver', 'dollar']
            )
            
            # Start a new financial section
            if is_financial_header or (has_dollar or has_percent or has_fee_number):
                # If we're already in a financial section and hit another financial header,
                # continue the current section (it's a sub-header like "Application Fee Waivers")
                if in_financial_section and is_financial_header and 'fee' in line_lower:
                    # This is a sub-header, add it to current section
                    current_section.append(line_stripped)
                elif in_financial_section and len(current_section) > 2:
                    # Save previous section
                    financial_sections.append('\n'.join(current_section))
                    in_financial_section = True
                    section_start_idx = i
                    current_section = [line_stripped]
                else:
                    in_financial_section = True
                    section_start_idx = i
                    current_section = [line_stripped]
            elif in_financial_section:
                # Check if we've hit a new major section (not financial)
                # Be more strict - only end if it's clearly a different topic
                is_new_section = (
                    line_lower and 
                    (line_lower.isupper() or len(line_lower) < 80) and
                    any(header in line_lower for header in ['application deadline', 'requirement', 'contact us', 'document', 'office of admission']) and
                    'fee' not in line_lower and 'financial' not in line_lower and 'waiver' not in line_lower and
                    i > section_start_idx + 5  # Only if we're well into the section
                )
                
                # Also check if this is clearly not financial content
                is_non_financial = (
                    line_lower and
                    any(phrase in line_lower for phrase in ['graduate degrees offered', 'visit', 'campus', 'tour', 'location']) and
                    'fee' not in line_lower and 'cost' not in line_lower
                )
                
                if (is_new_section or is_non_financial) and len(current_section) > 3:
                    # End current section
                    financial_sections.append('\n'.join(current_section))
                    current_section = []
                    in_financial_section = False
                elif line_stripped:
                    # Continue current section - include all lines that might be part of financial info
                    # Include if it has financial keywords, is a list item, or is substantial content
                    has_financial_word = any(word in line_lower for word in ['fee', 'waiver', 'cost', 'tuition', 'dollar', '$', 'application', 'financial', 'aid', 'scholarship', 'students attending', 'alumni', 'military', 'participants'])
                    is_list_item = bool(re.match(r'^\d+\.|^[-•*]|^[a-z]\)', line_stripped))
                    # Also include lines that are clearly part of waiver descriptions
                    is_waiver_detail = any(phrase in line_lower for phrase in ['automatically waived', 'eligible for', 'fee waiver', 'waiver program'])
                    
                    if has_financial_word or is_list_item or is_waiver_detail or (len(line_stripped) > 15 and i < section_start_idx + 30):
                        # Include if it's within reasonable distance of section start
                        current_section.append(line_stripped)
                elif len(current_section) > 0 and i < len(lines) - 1:
                    # Empty line, but check if next line continues the section
                    next_line = lines[i + 1].strip().lower() if i + 1 < len(lines) else ''
                    if not next_line or any(word in next_line for word in ['fee', 'waiver', 'cost', 'tuition', 'dollar', '$', 'application', 'financial']):
                        # Continue section
                        if line_stripped == '':
                            current_section.append('')
                    elif len(current_section) > 5:
                        # End section after empty line only if we have substantial content
                        financial_sections.append('\n'.join(current_section))
                        current_section = []
                        in_financial_section = False
        
        # Add last section if exists
        if current_section and len(current_section) > 2:
            financial_sections.append('\n'.join(current_section))
        
        # Filter sections to only include those with actual financial numbers
        filtered_sections = []
        for section in financial_sections:
            # Must contain dollar amounts, percentages, or specific fee numbers
            if (re.search(dollar_pattern, section) or 
                re.search(percent_pattern, section) or
                (re.search(r'\b(?:75|50|100|25|200|500|1000|5000)\b', section) and 
                 any(word in section.lower() for word in ['fee', 'cost', 'tuition', 'application']))):
                filtered_sections.append(section)
        
        if filtered_sections:
            return '\n\n---\n\n'.join(filtered_sections[:5])  # Top 5 sections with actual numbers
        return None
    
    def save_admissions_data(self, page_title: str, data: Dict[str, Optional[str]]):
        """
        Save admissions data to files.
        
        Args:
            page_title: Title/name of the page (will be sanitized for folder name)
            data: Dictionary containing content, requirements, deadlines, contact_info, financial_info
        """
        # Skip saving if no content (page doesn't exist or error)
        if not data.get('content'):
            logger.info(f"Skipping save for {page_title} - no content")
            return
        
        safe_name = self._sanitize_filename(page_title)
        page_dir = self.output_dir / safe_name
        page_dir.mkdir(parents=True, exist_ok=True)
        
        # Save main content
        if data.get('content'):
            content_file = page_dir / "content.txt"
            content_file.write_text(data['content'], encoding='utf-8')
            logger.info(f"Saved content to {content_file}")
        
        # Save requirements
        if data.get('requirements'):
            requirements_file = page_dir / "requirements.txt"
            requirements_file.write_text(data['requirements'], encoding='utf-8')
            logger.info(f"Saved requirements to {requirements_file}")
        
        # Save deadlines
        if data.get('deadlines'):
            deadlines_file = page_dir / "deadlines.txt"
            deadlines_file.write_text(data['deadlines'], encoding='utf-8')
            logger.info(f"Saved deadlines to {deadlines_file}")
        
        # Save contact info
        if data.get('contact_info'):
            contact_file = page_dir / "contact_info.txt"
            contact_file.write_text(data['contact_info'], encoding='utf-8')
            logger.info(f"Saved contact info to {contact_file}")
        
        # Save financial info
        if data.get('financial_info'):
            financial_file = page_dir / "financial_info.txt"
            financial_file.write_text(data['financial_info'], encoding='utf-8')
            logger.info(f"Saved financial info to {financial_file}")
    
    async def _scrape_single_page(self, browser: Browser, url: str, title: str):
        """Scrape a single admissions page with semaphore control."""
        async with self.semaphore:
            try:
                context = await browser.new_context()
                page = await context.new_page()
                
                # Determine if we should follow links (for main admissions pages)
                follow_links = 'main_admissions' in title.lower() or ('admissions' in title.lower() and 'main' in title.lower())
                
                # Scrape page
                visited_urls = set()
                data = await self.scrape_admissions_page(
                    page, 
                    url, 
                    follow_links=False,  # We'll handle link following separately
                    visited_urls=visited_urls,
                    max_link_depth=0
                )
                
                # If we should follow links, scrape linked financial pages
                if follow_links and data.get('content'):
                    financial_links = await self._find_financial_links(page, url)
                    logger.info(f"Found {len(financial_links)} financial-related links from {url}")
                    
                    linked_financial_info = []
                    for link_url, link_title in financial_links[:5]:  # Limit to 5 links
                        if link_url not in visited_urls:
                            try:
                                await self._rate_limit()
                                linked_context = await browser.new_context()
                                linked_page = await linked_context.new_page()
                                
                                linked_data = await self.scrape_admissions_page(
                                    linked_page, 
                                    link_url, 
                                    follow_links=False,
                                    visited_urls=visited_urls,
                                    max_link_depth=0
                                )
                                await linked_context.close()
                                
                                # Aggregate financial info from linked page
                                # Also include content if it has financial keywords, even without dollar amounts
                                if linked_data.get('financial_info'):
                                    linked_financial_info.append(f"From {link_title} ({link_url}):\n{linked_data['financial_info']}")
                                elif linked_data.get('content'):
                                    # Check if content has financial keywords
                                    content_lower = linked_data['content'].lower()
                                    financial_keywords_in_content = any(
                                        keyword in content_lower 
                                        for keyword in ['cost', 'tuition', 'fee', 'scholarship', 'financial aid', 'funding', 'price']
                                    )
                                    if financial_keywords_in_content:
                                        # Extract relevant sections with financial keywords
                                        lines = linked_data['content'].split('\n')
                                        relevant_lines = [
                                            line.strip() for line in lines 
                                            if any(keyword in line.lower() for keyword in ['cost', 'tuition', 'fee', 'scholarship', 'financial', 'funding', 'price', 'aid'])
                                            and len(line.strip()) > 10
                                        ]
                                        if relevant_lines:
                                            linked_financial_info.append(
                                                f"From {link_title} ({link_url}):\n" + 
                                                '\n'.join(relevant_lines[:20])  # Limit to 20 lines
                                            )
                            except Exception as e:
                                logger.warning(f"Error following link {link_url}: {e}")
                                continue
                    
                    # Combine financial info
                    if linked_financial_info:
                        if data.get('financial_info'):
                            data['financial_info'] = f"{data['financial_info']}\n\n---\n\n" + "\n\n---\n\n".join(linked_financial_info)
                        else:
                            data['financial_info'] = "\n\n---\n\n".join(linked_financial_info)
                
                # Save data
                self.save_admissions_data(title, data)
                
                await context.close()
                
            except Exception as e:
                logger.error(f"Error scraping {title} ({url}): {e}")
    
    async def scrape(self):
        """Main scraping method. Overrides parent to use admissions-specific methods."""
        from playwright.async_api import async_playwright
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            
            try:
                # Create a page to find all admissions links
                page = await browser.new_page()
                admissions_links = await self.find_admissions_links(page)
                await page.close()
                
                # Limit pages if specified
                if self.max_pages:
                    admissions_links = admissions_links[:self.max_pages]
                
                logger.info(f"Scraping {len(admissions_links)} admissions pages...")
                
                # Scrape all pages in parallel (with semaphore limit)
                tasks = [
                    self._scrape_single_page(browser, url, title)
                    for url, title in admissions_links
                ]
                await asyncio.gather(*tasks, return_exceptions=True)
                
            finally:
                await browser.close()
            
            logger.info("Admissions scraping completed!")


"""
Test script to verify scraper works with a single page.
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path to allow importing scraper
sys.path.insert(0, str(Path(__file__).parent.parent))


async def main():
    scraper = UTDAdmissionsScraper(
        max_pages=None,  # Scrape all found pages
        rate_limit=2.0,
        max_parallel=3,
        output_dir="./data/admissions"
    )
    
    await scraper.scrape()
    print("Test completed! Check ./data/admissions for results.")


if __name__ == "__main__":
    asyncio.run(main())


