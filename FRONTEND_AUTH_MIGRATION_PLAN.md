# Frontend Authentication Migration Plan

## 🎯 Overview

This document provides step-by-step instructions to migrate Supabase authentication from the incorrectly created `gift-ai-backend/frontend/` directory to the correct `gift-ai-frontend/` project on Railway.

**Current (WRONG):** `C:\Users\camry\PycharmProjects\PythonProject\gift-ai-backend\frontend\`
**Target (CORRECT):** `C:\Users\camry\PycharmProjects\PythonProject\gift-ai-frontend\`

---

## 📋 Task 1: Complete File Inventory

### Files in `gift-ai-backend/frontend/` (21 files total)

#### ✅ Files to COPY Directly (13 files)

| File | Purpose | Action |
|------|---------|--------|
| `app/login/page.tsx` | Login page with email/password + Google OAuth | **COPY** - Add to target |
| `app/signup/page.tsx` | Signup page with validation | **COPY** - Add to target |
| `app/profile/page.tsx` | Protected user profile page | **COPY** - Add to target |
| `app/auth/callback/route.ts` | OAuth callback handler | **COPY** - Add to target |
| `contexts/AuthContext.tsx` | Auth state management | **COPY** - Add to target |
| `lib/supabase/client.ts` | Client-side Supabase client | **COPY** - Add to target |
| `lib/supabase/server.ts` | Server-side Supabase client | **COPY** - Add to target |
| `middleware.ts` | Protected routes middleware | **COPY** - Add to target |
| `types/database.ts` | TypeScript database types | **COPY** - Add to target |
| `tailwind.config.ts` | Tailwind v3 config | **SKIP** - Target uses v4 |
| `.env.local.example` | Environment template | **MERGE** - Add Supabase vars |
| `AUTH_SETUP_GUIDE.md` | Setup documentation | **COPY** - Add to target |
| `README.md` | Frontend README | **SKIP** - Keep existing |

#### ⚠️ Files to MERGE Carefully (3 files)

| File | Existing (Target) | Created (Source) | Action |
|------|-------------------|------------------|--------|
| `app/layout.tsx` | Uses Geist fonts, no auth | Uses Inter font, has AuthProvider | **MERGE** - Add AuthProvider, keep Geist fonts |
| `app/page.tsx` | Gift search page (KEEP!) | Generic auth home page | **SKIP** - Do NOT overwrite! |
| `app/globals.css` | Tailwind v4 syntax | Tailwind v3 syntax | **KEEP EXISTING** - Target is correct |

#### 🗑️ Files to SKIP (5 files)

| File | Reason |
|------|--------|
| `next.config.js` | Target already has `next.config.ts` |
| `package.json` | Will merge dependencies only |
| `postcss.config.js` | Target already has `postcss.config.mjs` |
| `tsconfig.json` | Target config is correct |
| `.gitignore` | Target already has this |

---

## 📦 Task 2: Migration Plan - File by File

### Phase 1: Create Directory Structure

```powershell
# Create new directories in target
New-Item -Path "C:\Users\camry\PycharmProjects\PythonProject\gift-ai-frontend\contexts" -ItemType Directory -Force
New-Item -Path "C:\Users\camry\PycharmProjects\PythonProject\gift-ai-frontend\lib\supabase" -ItemType Directory -Force
New-Item -Path "C:\Users\camry\PycharmProjects\PythonProject\gift-ai-frontend\types" -ItemType Directory -Force
New-Item -Path "C:\Users\camry\PycharmProjects\PythonProject\gift-ai-frontend\app\login" -ItemType Directory -Force
New-Item -Path "C:\Users\camry\PycharmProjects\PythonProject\gift-ai-frontend\app\signup" -ItemType Directory -Force
New-Item -Path "C:\Users\camry\PycharmProjects\PythonProject\gift-ai-frontend\app\profile" -ItemType Directory -Force
New-Item -Path "C:\Users\camry\PycharmProjects\PythonProject\gift-ai-frontend\app\auth\callback" -ItemType Directory -Force
```

### Phase 2: Copy Auth Pages

```powershell
# Copy authentication pages
Copy-Item -Path "C:\Users\camry\PycharmProjects\PythonProject\gift-ai-backend\frontend\app\login\page.tsx" -Destination "C:\Users\camry\PycharmProjects\PythonProject\gift-ai-frontend\app\login\page.tsx"

Copy-Item -Path "C:\Users\camry\PycharmProjects\PythonProject\gift-ai-backend\frontend\app\signup\page.tsx" -Destination "C:\Users\camry\PycharmProjects\PythonProject\gift-ai-frontend\app\signup\page.tsx"

Copy-Item -Path "C:\Users\camry\PycharmProjects\PythonProject\gift-ai-frontend\app\profile\page.tsx" -Destination "C:\Users\camry\PycharmProjects\PythonProject\gift-ai-frontend\app\profile\page.tsx"

Copy-Item -Path "C:\Users\camry\PycharmProjects\PythonProject\gift-ai-backend\frontend\app\auth\callback\route.ts" -Destination "C:\Users\camry\PycharmProjects\PythonProject\gift-ai-frontend\app\auth\callback\route.ts"
```

### Phase 3: Copy Auth Infrastructure

```powershell
# Copy contexts
Copy-Item -Path "C:\Users\camry\PycharmProjects\PythonProject\gift-ai-backend\frontend\contexts\AuthContext.tsx" -Destination "C:\Users\camry\PycharmProjects\PythonProject\gift-ai-frontend\contexts\AuthContext.tsx"

# Copy Supabase utilities
Copy-Item -Path "C:\Users\camry\PycharmProjects\PythonProject\gift-ai-backend\frontend\lib\supabase\client.ts" -Destination "C:\Users\camry\PycharmProjects\PythonProject\gift-ai-frontend\lib\supabase\client.ts"

Copy-Item -Path "C:\Users\camry\PycharmProjects\PythonProject\gift-ai-backend\frontend\lib\supabase\server.ts" -Destination "C:\Users\camry\PycharmProjects\PythonProject\gift-ai-frontend\lib\supabase\server.ts"

# Copy middleware
Copy-Item -Path "C:\Users\camry\PycharmProjects\PythonProject\gift-ai-backend\frontend\middleware.ts" -Destination "C:\Users\camry\PycharmProjects\PythonProject\gift-ai-frontend\middleware.ts"

# Copy types
Copy-Item -Path "C:\Users\camry\PycharmProjects\PythonProject\gift-ai-backend\frontend\types\database.ts" -Destination "C:\Users\camry\PycharmProjects\PythonProject\gift-ai-frontend\types\database.ts"
```

### Phase 4: Copy Documentation

```powershell
# Copy authentication setup guide
Copy-Item -Path "C:\Users\camry\PycharmProjects\PythonProject\gift-ai-backend\frontend\AUTH_SETUP_GUIDE.md" -Destination "C:\Users\camry\PycharmProjects\PythonProject\gift-ai-frontend\AUTH_SETUP_GUIDE.md"
```

### Phase 5: Update Environment Variables

**DO NOT COPY .env.local** - Instead, manually add to existing `.env.local`:

```env
# Supabase Configuration (ADD THESE)
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your-anon-key-here
NEXT_PUBLIC_SITE_URL=http://localhost:3000
```

### Phase 6: Merge app/layout.tsx

**MANUAL EDIT REQUIRED** - Update existing layout to add AuthProvider:

**Current content** (keep Geist fonts):
```tsx
import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Create Next App",
  description: "Generated by create next app",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased`}
      >
        {children}
      </body>
    </html>
  );
}
```

**NEW content** (add AuthProvider import and wrapper):
```tsx
import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { AuthProvider } from '@/contexts/AuthContext'  // ← ADD THIS

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Gift AI - Smart Gift Recommendations",  // ← UPDATE THIS
  description: "AI-powered gift recommendations for every occasion",  // ← UPDATE THIS
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased`}
      >
        <AuthProvider>{children}</AuthProvider>  {/* ← WRAP children */}
      </body>
    </html>
  );
}
```

### Phase 7: Install Dependencies

**DO NOT copy package.json!** Instead, install the required auth packages:

```powershell
cd C:\Users\camry\PycharmProjects\PythonProject\gift-ai-frontend

# Install Supabase auth packages
npm install @supabase/supabase-js@latest
npm install @supabase/auth-helpers-nextjs@latest
npm install @supabase/ssr@latest
```

**Note:** The target already has these installed, but they may need updating to latest versions.

### Phase 8: Cleanup - Delete Wrong Frontend

**⚠️ ONLY after verifying everything works:**

```powershell
# Remove the entire wrongly created frontend folder
Remove-Item -Path "C:\Users\camry\PycharmProjects\PythonProject\gift-ai-backend\frontend" -Recurse -Force
```

---

## 💻 Task 3: PowerShell Migration Script

**Complete migration script** (run from PowerShell as Administrator):

```powershell
# Variables
$source = "C:\Users\camry\PycharmProjects\PythonProject\gift-ai-backend\frontend"
$target = "C:\Users\camry\PycharmProjects\PythonProject\gift-ai-frontend"

Write-Host "🚀 Starting Frontend Auth Migration..." -ForegroundColor Cyan

# Step 1: Create directories
Write-Host "`n📁 Creating directory structure..." -ForegroundColor Yellow
New-Item -Path "$target\contexts" -ItemType Directory -Force | Out-Null
New-Item -Path "$target\lib\supabase" -ItemType Directory -Force | Out-Null
New-Item -Path "$target\types" -ItemType Directory -Force | Out-Null
New-Item -Path "$target\app\login" -ItemType Directory -Force | Out-Null
New-Item -Path "$target\app\signup" -ItemType Directory -Force | Out-Null
New-Item -Path "$target\app\profile" -ItemType Directory -Force | Out-Null
New-Item -Path "$target\app\auth\callback" -ItemType Directory -Force | Out-Null
Write-Host "✅ Directories created" -ForegroundColor Green

# Step 2: Copy auth pages
Write-Host "`n📄 Copying authentication pages..." -ForegroundColor Yellow
Copy-Item -Path "$source\app\login\page.tsx" -Destination "$target\app\login\page.tsx" -Force
Copy-Item -Path "$source\app\signup\page.tsx" -Destination "$target\app\signup\page.tsx" -Force
Copy-Item -Path "$source\app\profile\page.tsx" -Destination "$target\app\profile\page.tsx" -Force
Copy-Item -Path "$source\app\auth\callback\route.ts" -Destination "$target\app\auth\callback\route.ts" -Force
Write-Host "✅ Auth pages copied (4 files)" -ForegroundColor Green

# Step 3: Copy infrastructure
Write-Host "`n🔧 Copying auth infrastructure..." -ForegroundColor Yellow
Copy-Item -Path "$source\contexts\AuthContext.tsx" -Destination "$target\contexts\AuthContext.tsx" -Force
Copy-Item -Path "$source\lib\supabase\client.ts" -Destination "$target\lib\supabase\client.ts" -Force
Copy-Item -Path "$source\lib\supabase\server.ts" -Destination "$target\lib\supabase\server.ts" -Force
Copy-Item -Path "$source\middleware.ts" -Destination "$target\middleware.ts" -Force
Copy-Item -Path "$source\types\database.ts" -Destination "$target\types\database.ts" -Force
Write-Host "✅ Infrastructure copied (5 files)" -ForegroundColor Green

# Step 4: Copy documentation
Write-Host "`n📚 Copying documentation..." -ForegroundColor Yellow
Copy-Item -Path "$source\AUTH_SETUP_GUIDE.md" -Destination "$target\AUTH_SETUP_GUIDE.md" -Force
Write-Host "✅ Documentation copied" -ForegroundColor Green

# Step 5: Copy env example (as reference)
Write-Host "`n🔐 Copying environment template..." -ForegroundColor Yellow
Copy-Item -Path "$source\.env.local.example" -Destination "$target\.env.local.example.supabase" -Force
Write-Host "✅ Environment template copied as .env.local.example.supabase" -ForegroundColor Green

Write-Host "`n✅ Migration complete!" -ForegroundColor Green
Write-Host "`n⚠️  MANUAL STEPS REQUIRED:" -ForegroundColor Red
Write-Host "1. Update app/layout.tsx to add AuthProvider (see migration plan)" -ForegroundColor White
Write-Host "2. Add Supabase environment variables to .env.local" -ForegroundColor White
Write-Host "3. Run: cd $target && npm install @supabase/supabase-js@latest @supabase/auth-helpers-nextjs@latest @supabase/ssr@latest" -ForegroundColor White
Write-Host "4. Test the application thoroughly" -ForegroundColor White
Write-Host "5. ONLY after testing: Remove-Item -Path '$source' -Recurse -Force" -ForegroundColor White
```

**To run the script:**

1. Save to a file: `migration-script.ps1`
2. Run: `powershell -ExecutionPolicy Bypass -File migration-script.ps1`

---

## 📦 Task 4: NPM Packages to Install

### Required Dependencies

The target `gift-ai-frontend` **already has** these packages but may need updates:

```json
{
  "dependencies": {
    "@supabase/supabase-js": "^2.39.3",           // ← Update to latest
    "@supabase/auth-helpers-nextjs": "^0.8.7",    // ← Update to latest
    "@supabase/auth-ui-react": "^0.4.7",          // ← Already installed
    "@supabase/auth-ui-shared": "^0.1.8",         // ← Already installed
    "@supabase/ssr": "^0.5.1",                    // ← ADD THIS (new package)
    "cookies-next": "^4.1.0"                      // ← Already installed
  }
}
```

### Installation Command

```bash
cd C:\Users\camry\PycharmProjects\PythonProject\gift-ai-frontend

# Install/update Supabase packages
npm install @supabase/supabase-js@latest @supabase/auth-helpers-nextjs@latest @supabase/ssr@latest
```

**Note:** Do NOT copy `package.json` - the target is using Next.js 16.1.4 and Tailwind v4, which are newer than the source.

---

## 🔐 Task 5: Updated .env.local.example

Create this in `gift-ai-frontend/.env.local.example`:

```env
# Backend API
NEXT_PUBLIC_API_URL=http://localhost:8000

# Supabase Configuration
# Get these from: Supabase Dashboard → Settings → API
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your-anon-public-key-here

# Site URL (for OAuth redirects)
# Development: http://localhost:3000
# Production: https://your-domain.com
NEXT_PUBLIC_SITE_URL=http://localhost:3000
```

**For your actual `.env.local`**, add these lines to the existing file:

```env
# Existing content (keep this)
NEXT_PUBLIC_API_URL=...

# ADD THESE NEW LINES:
NEXT_PUBLIC_SUPABASE_URL=https://your-actual-project.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your-actual-anon-key
NEXT_PUBLIC_SITE_URL=http://localhost:3000
```

---

## 🔨 Task 6: Code Integration Changes

### Change 1: Update `app/layout.tsx`

**File:** `gift-ai-frontend/app/layout.tsx`

**Add import:**
```tsx
import { AuthProvider } from '@/contexts/AuthContext'
```

**Wrap children:**
```tsx
<body className={`${geistSans.variable} ${geistMono.variable} antialiased`}>
  <AuthProvider>{children}</AuthProvider>
</body>
```

**Full updated file:**
```tsx
import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { AuthProvider } from '@/contexts/AuthContext'

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Gift AI - Smart Gift Recommendations",
  description: "AI-powered gift recommendations for every occasion",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased`}
      >
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
```

### Change 2: Add Optional User Navigation (OPTIONAL)

**File:** `gift-ai-frontend/app/page.tsx`

You can optionally add a user menu to show login/profile status. Add this at the top of the page:

```tsx
'use client'

import { useState } from "react";
import { useAuth } from '@/contexts/AuthContext'  // ← ADD THIS
import Link from 'next/link'  // ← ADD THIS

// ... existing Gift type ...

export default function Home() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Gift[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const { user, loading: authLoading } = useAuth()  // ← ADD THIS

  // ... existing functions ...

  return (
    <main className="min-h-screen bg-slate-50 px-6 py-12">
      <div className="mx-auto max-w-4xl">
        {/* ADD THIS: Optional user menu */}
        {!authLoading && (
          <div className="flex justify-end mb-4">
            {user ? (
              <Link
                href="/profile"
                className="text-sm text-slate-600 hover:text-slate-900"
              >
                👤 {user.email}
              </Link>
            ) : (
              <Link
                href="/login"
                className="text-sm text-slate-600 hover:text-slate-900"
              >
                Login
              </Link>
            )}
          </div>
        )}

        {/* Existing content below... */}
        <h1 className="text-4xl font-bold text-slate-900 mb-2">
          🎁 AI Gift Finder
        </h1>
        {/* ... rest of existing code ... */}
      </div>
    </main>
  );
}
```

**Important:** This navigation is **OPTIONAL**. Users can search for gifts without logging in. Authentication is only required for protected routes like `/profile`.

### Change 3: No Changes to Middleware

The copied `middleware.ts` should work as-is. It will:
- Allow anonymous access to `/` (gift search)
- Allow anonymous access to `/login`, `/signup`
- Protect `/profile` (redirect to login if not authenticated)

---

## ✅ Task 7: Testing Checklist

### Pre-Migration Checklist

- [ ] Backup existing `gift-ai-frontend` directory
- [ ] Ensure no uncommitted changes in git
- [ ] Note current working state of gift search

### Post-Migration Checklist

#### 1. Installation Verification
- [ ] Run `npm install` in gift-ai-frontend
- [ ] Check for dependency conflicts
- [ ] Run `npm run dev` - should start without errors

#### 2. Existing Functionality (CRITICAL)
- [ ] Navigate to `http://localhost:3000`
- [ ] Gift search page loads correctly
- [ ] Can enter search query
- [ ] Click "Find Gifts" button works
- [ ] Results display correctly
- [ ] All existing features work (no regressions)

#### 3. Authentication Pages
- [ ] Navigate to `http://localhost:3000/login`
- [ ] Login page loads with email/password form
- [ ] "Sign in with Google" button visible
- [ ] Navigate to `http://localhost:3000/signup`
- [ ] Signup page loads correctly
- [ ] Form validation works

#### 4. Supabase Integration
- [ ] Environment variables loaded (check console for errors)
- [ ] Can create new account (signup flow)
- [ ] Receive verification email
- [ ] Can log in with email/password
- [ ] Session persists on page refresh
- [ ] Can access `/profile` when logged in

#### 5. Protected Routes
- [ ] Try accessing `/profile` while logged out → redirects to `/login`
- [ ] Log in successfully → redirect to home
- [ ] Access `/profile` while logged in → shows profile page
- [ ] Can edit profile name
- [ ] Can log out

#### 6. Google OAuth (if configured)
- [ ] Click "Sign in with Google"
- [ ] Redirects to Google login
- [ ] After Google auth, returns to app
- [ ] Session created successfully
- [ ] User data visible in `/profile`

#### 7. Anonymous Access (CRITICAL)
- [ ] Can use gift search WITHOUT logging in
- [ ] No authentication errors on home page
- [ ] Authentication is truly optional

#### 8. Console & Network
- [ ] No TypeScript errors in build
- [ ] No console errors in browser
- [ ] No 404s for auth routes
- [ ] Middleware runs correctly (check Network tab)

#### 9. Build Test
- [ ] Run `npm run build`
- [ ] Build succeeds without errors
- [ ] Run `npm run start`
- [ ] Production build works correctly

#### 10. Cleanup
- [ ] All tests pass
- [ ] Commit changes to git
- [ ] Delete `gift-ai-backend/frontend/` folder

---

## 🚨 Common Issues & Solutions

### Issue 1: "Cannot find module '@/contexts/AuthContext'"

**Solution:** Ensure `contexts/` folder was created and `AuthContext.tsx` was copied.

```powershell
# Verify file exists
Test-Path "C:\Users\camry\PycharmProjects\PythonProject\gift-ai-frontend\contexts\AuthContext.tsx"
```

### Issue 2: Middleware causing redirect loop

**Solution:** Check `middleware.ts` matcher config excludes static files:

```tsx
export const config = {
  matcher: [
    '/((?!_next/static|_next/image|favicon.ico|public).*)',
  ],
}
```

### Issue 3: Supabase environment variables not found

**Solution:** Restart dev server after adding env vars:

```bash
# Stop dev server (Ctrl+C)
npm run dev  # Restart
```

### Issue 4: TypeScript errors about Supabase types

**Solution:** Ensure `types/database.ts` was copied and update imports:

```tsx
import type { Database } from '@/types/database'
```

### Issue 5: Tailwind styles not working on auth pages

**Solution:** The existing `globals.css` uses Tailwind v4 syntax and should work. If issues persist:

```css
/* globals.css should have */
@import "tailwindcss";
```

NOT the old v3 syntax:
```css
@tailwind base;  /* ← Don't use this */
```

---

## 📊 Migration Summary

### Files Migrated: 13
- ✅ 4 Auth pages (login, signup, profile, callback)
- ✅ 1 Auth context (AuthContext.tsx)
- ✅ 2 Supabase utilities (client.ts, server.ts)
- ✅ 1 Middleware (middleware.ts)
- ✅ 1 Types file (database.ts)
- ✅ 1 Documentation (AUTH_SETUP_GUIDE.md)
- ✅ 1 Environment template (.env.local.example)
- ⚠️ 1 Manual merge (app/layout.tsx)
- ✅ 1 Optional update (app/page.tsx for user menu)

### Files Preserved: 7
- ✅ app/page.tsx (existing gift search)
- ✅ app/globals.css (Tailwind v4 config)
- ✅ package.json (merged dependencies)
- ✅ next.config.ts
- ✅ tsconfig.json
- ✅ postcss.config.mjs
- ✅ .gitignore

### Files Deleted After Migration: 1 directory
- 🗑️ `gift-ai-backend/frontend/` (entire folder)

---

## 🎯 Success Criteria

Your migration is successful when:

1. ✅ Gift search works exactly as before (no regressions)
2. ✅ Users can search gifts without logging in
3. ✅ Login page accessible at `/login`
4. ✅ Signup page accessible at `/signup`
5. ✅ Can create account and log in
6. ✅ Profile page protected (requires login)
7. ✅ Sessions persist across page refreshes
8. ✅ Google OAuth works (if configured)
9. ✅ No console errors
10. ✅ Build succeeds (`npm run build`)
11. ✅ Old frontend folder deleted

---

## 📝 Next Steps After Migration

1. **Configure Supabase** (follow AUTH_SETUP_GUIDE.md)
   - Enable email provider
   - Enable Google OAuth (optional)
   - Set Site URL and Redirect URLs

2. **Test thoroughly** using the checklist above

3. **Deploy to Railway**
   - Add environment variables to Railway
   - Update Supabase URLs to production
   - Test production authentication

4. **Optional Enhancements**
   - Add "Favorites" feature (save gifts to user account)
   - Add "Search History" for logged-in users
   - Add user preferences for gift recommendations

---

**Migration plan created:** `C:\Users\camry\PycharmProjects\PythonProject\gift-ai-backend\FRONTEND_AUTH_MIGRATION_PLAN.md`

**Ready to execute!** Follow the PowerShell script in Task 3, then complete the manual steps in Task 6.
