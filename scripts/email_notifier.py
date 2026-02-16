#!/usr/bin/env python3
"""
Email Notifier Module
=====================
Sends email notifications with detailed reports using SMTP.
"""

import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class EmailNotifier:
    """Send email notifications for price update workflows."""

    def __init__(
        self,
        smtp_host: str = None,
        smtp_port: int = None,
        smtp_user: str = None,
        smtp_password: str = None,
        from_email: str = None,
        to_emails: List[str] = None
    ):
        self.smtp_host = smtp_host or os.environ.get('SMTP_HOST', 'smtp.gmail.com')
        self.smtp_port = smtp_port or int(os.environ.get('SMTP_PORT', '587'))
        self.smtp_user = smtp_user or os.environ.get('SMTP_USER', '')
        self.smtp_password = smtp_password or os.environ.get('SMTP_PASSWORD', '')
        self.from_email = from_email or os.environ.get('FROM_EMAIL', self.smtp_user)
        self.to_emails = to_emails or os.environ.get('TO_EMAILS', '').split(',')

    def send_report(
        self,
        subject: str,
        workflow_type: str,
        summary: Dict,
        details: List[Dict] = None,
        errors: List[Dict] = None
    ) -> bool:
        """
        Send an email report.

        Args:
            subject: Email subject
            workflow_type: Type of workflow (automatic, manual, diamond)
            summary: Summary statistics dict
            details: List of detail dicts for successful updates
            errors: List of error dicts

        Returns:
            True if sent successfully, False otherwise
        """
        if not self.smtp_user or not self.smtp_password:
            logger.warning("SMTP credentials not configured, skipping email notification")
            return False

        if not self.to_emails or not self.to_emails[0]:
            logger.warning("No recipient emails configured, skipping email notification")
            return False

        try:
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = self.from_email
            msg['To'] = ', '.join(self.to_emails)

            # Build HTML content
            html_content = self._build_html_report(workflow_type, summary, details, errors)
            text_content = self._build_text_report(workflow_type, summary, details, errors)

            msg.attach(MIMEText(text_content, 'plain'))
            msg.attach(MIMEText(html_content, 'html'))

            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_user, self.smtp_password)
                server.sendmail(self.from_email, self.to_emails, msg.as_string())

            logger.info(f"Email notification sent to {', '.join(self.to_emails)}")
            return True

        except Exception as e:
            logger.error(f"Failed to send email notification: {str(e)}")
            return False

    def _build_html_report(
        self,
        workflow_type: str,
        summary: Dict,
        details: List[Dict] = None,
        errors: List[Dict] = None
    ) -> str:
        """Build HTML email report."""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        html = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        h1 {{ color: #333; }}
        h2 {{ color: #666; margin-top: 30px; }}
        .summary {{ background: #f5f5f5; padding: 20px; border-radius: 8px; margin: 20px 0; }}
        .summary-item {{ margin: 10px 0; }}
        .summary-label {{ font-weight: bold; color: #555; }}
        .summary-value {{ color: #333; }}
        .success {{ color: #28a745; }}
        .error {{ color: #dc3545; }}
        .warning {{ color: #ffc107; }}
        table {{ border-collapse: collapse; width: 100%; margin: 20px 0; }}
        th, td {{ border: 1px solid #ddd; padding: 12px; text-align: left; }}
        th {{ background: #f8f9fa; font-weight: bold; }}
        tr:nth-child(even) {{ background: #f9f9f9; }}
        .footer {{ margin-top: 40px; padding-top: 20px; border-top: 1px solid #ddd; color: #888; font-size: 12px; }}
    </style>
</head>
<body>
    <h1>Shopify Price Update Report</h1>
    <p><strong>Workflow:</strong> {workflow_type}</p>
    <p><strong>Timestamp:</strong> {timestamp}</p>

    <div class="summary">
        <h2>Summary</h2>
"""

        for key, value in summary.items():
            label = key.replace('_', ' ').title()
            css_class = ''
            if 'success' in key.lower():
                css_class = 'success'
            elif 'error' in key.lower() or 'failed' in key.lower():
                css_class = 'error'
            html += f'<div class="summary-item"><span class="summary-label">{label}:</span> <span class="summary-value {css_class}">{value}</span></div>\n'

        html += "</div>"

        if details and len(details) > 0:
            html += """
    <h2>Update Details</h2>
    <table>
        <tr>
            <th>Product</th>
            <th>Variant</th>
            <th>Old Price</th>
            <th>New Price</th>
            <th>Compare At</th>
        </tr>
"""
            for detail in details[:100]:  # Limit to 100 rows
                html += f"""
        <tr>
            <td>{detail.get('product_title', 'N/A')}</td>
            <td>{detail.get('variant_title', 'N/A')}</td>
            <td>{detail.get('old_price', 'N/A')}</td>
            <td>{detail.get('new_price', 'N/A')}</td>
            <td>{detail.get('compare_at_price', 'N/A')}</td>
        </tr>
"""
            if len(details) > 100:
                html += f'<tr><td colspan="5">... and {len(details) - 100} more updates</td></tr>'
            html += "</table>"

        if errors and len(errors) > 0:
            html += """
    <h2 class="error">Errors</h2>
    <table>
        <tr>
            <th>Product/Variant</th>
            <th>Error</th>
        </tr>
"""
            for error in errors[:50]:
                html += f"""
        <tr>
            <td>{error.get('variant_id', error.get('product_id', 'N/A'))}</td>
            <td class="error">{error.get('error', error.get('errors', 'Unknown error'))}</td>
        </tr>
"""
            if len(errors) > 50:
                html += f'<tr><td colspan="2">... and {len(errors) - 50} more errors</td></tr>'
            html += "</table>"

        html += """
    <div class="footer">
        <p>This is an automated message from Shopify Price Updater.</p>
    </div>
</body>
</html>
"""
        return html

    def _build_text_report(
        self,
        workflow_type: str,
        summary: Dict,
        details: List[Dict] = None,
        errors: List[Dict] = None
    ) -> str:
        """Build plain text email report."""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        text = f"""
SHOPIFY PRICE UPDATE REPORT
===========================

Workflow: {workflow_type}
Timestamp: {timestamp}

SUMMARY
-------
"""
        for key, value in summary.items():
            label = key.replace('_', ' ').title()
            text += f"{label}: {value}\n"

        if details and len(details) > 0:
            text += f"\nUPDATE DETAILS ({len(details)} updates)\n"
            text += "-" * 40 + "\n"
            for detail in details[:20]:
                text += f"- {detail.get('product_title', 'N/A')} / {detail.get('variant_title', 'N/A')}: "
                text += f"{detail.get('old_price', 'N/A')} -> {detail.get('new_price', 'N/A')}\n"
            if len(details) > 20:
                text += f"... and {len(details) - 20} more updates\n"

        if errors and len(errors) > 0:
            text += f"\nERRORS ({len(errors)} errors)\n"
            text += "-" * 40 + "\n"
            for error in errors[:10]:
                text += f"- {error.get('variant_id', error.get('product_id', 'N/A'))}: {error.get('error', 'Unknown')}\n"
            if len(errors) > 10:
                text += f"... and {len(errors) - 10} more errors\n"

        text += "\n---\nThis is an automated message from Shopify Price Updater.\n"
        return text
