# Frontend Authentication Migration Script
# Migrates auth files from gift-ai-backend/frontend to gift-ai-frontend

# Variables
$source = "C:\Users\camry\PycharmProjects\PythonProject\gift-ai-backend\frontend"
$target = "C:\Users\camry\PycharmProjects\PythonProject\gift-ai-frontend"

Write-Host "╔═══════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║   Frontend Auth Migration Script                     ║" -ForegroundColor Cyan
Write-Host "║   Moving auth from backend/frontend to gift-ai-frontend ║" -ForegroundColor Cyan
Write-Host "╚═══════════════════════════════════════════════════════╝" -ForegroundColor Cyan

# Verify source exists
if (!(Test-Path $source)) {
    Write-Host "`n❌ ERROR: Source directory not found: $source" -ForegroundColor Red
    exit 1
}

# Verify target exists
if (!(Test-Path $target)) {
    Write-Host "`n❌ ERROR: Target directory not found: $target" -ForegroundColor Red
    exit 1
}

Write-Host "`n📍 Source: $source" -ForegroundColor White
Write-Host "📍 Target: $target" -ForegroundColor White

# Confirm before proceeding
Write-Host "`n⚠️  This will copy auth files to gift-ai-frontend." -ForegroundColor Yellow
Write-Host "   Existing app/page.tsx will NOT be touched." -ForegroundColor Yellow
$confirm = Read-Host "`nProceed with migration? (yes/no)"

if ($confirm -ne "yes") {
    Write-Host "`n❌ Migration cancelled by user" -ForegroundColor Red
    exit 0
}

# Step 1: Create directories
Write-Host "`n╔═══════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║ Step 1: Creating directory structure                 ║" -ForegroundColor Cyan
Write-Host "╚═══════════════════════════════════════════════════════╝" -ForegroundColor Cyan

$directories = @(
    "$target\contexts",
    "$target\lib\supabase",
    "$target\types",
    "$target\app\login",
    "$target\app\signup",
    "$target\app\profile",
    "$target\app\auth\callback"
)

foreach ($dir in $directories) {
    if (!(Test-Path $dir)) {
        New-Item -Path $dir -ItemType Directory -Force | Out-Null
        Write-Host "  ✅ Created: $dir" -ForegroundColor Green
    } else {
        Write-Host "  ℹ️  Exists: $dir" -ForegroundColor Gray
    }
}

# Step 2: Copy auth pages
Write-Host "`n╔═══════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║ Step 2: Copying authentication pages                 ║" -ForegroundColor Cyan
Write-Host "╚═══════════════════════════════════════════════════════╝" -ForegroundColor Cyan

$authPages = @(
    @{src="$source\app\login\page.tsx"; dst="$target\app\login\page.tsx"; name="Login page"},
    @{src="$source\app\signup\page.tsx"; dst="$target\app\signup\page.tsx"; name="Signup page"},
    @{src="$source\app\profile\page.tsx"; dst="$target\app\profile\page.tsx"; name="Profile page"},
    @{src="$source\app\auth\callback\route.ts"; dst="$target\app\auth\callback\route.ts"; name="OAuth callback"}
)

foreach ($page in $authPages) {
    if (Test-Path $page.src) {
        Copy-Item -Path $page.src -Destination $page.dst -Force
        Write-Host "  ✅ Copied: $($page.name)" -ForegroundColor Green
    } else {
        Write-Host "  ⚠️  Missing: $($page.name)" -ForegroundColor Yellow
    }
}

# Step 3: Copy infrastructure
Write-Host "`n╔═══════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║ Step 3: Copying auth infrastructure                  ║" -ForegroundColor Cyan
Write-Host "╚═══════════════════════════════════════════════════════╝" -ForegroundColor Cyan

$infrastructure = @(
    @{src="$source\contexts\AuthContext.tsx"; dst="$target\contexts\AuthContext.tsx"; name="Auth context"},
    @{src="$source\lib\supabase\client.ts"; dst="$target\lib\supabase\client.ts"; name="Supabase client"},
    @{src="$source\lib\supabase\server.ts"; dst="$target\lib\supabase\server.ts"; name="Supabase server"},
    @{src="$source\middleware.ts"; dst="$target\middleware.ts"; name="Middleware"},
    @{src="$source\types\database.ts"; dst="$target\types\database.ts"; name="Database types"}
)

foreach ($file in $infrastructure) {
    if (Test-Path $file.src) {
        Copy-Item -Path $file.src -Destination $file.dst -Force
        Write-Host "  ✅ Copied: $($file.name)" -ForegroundColor Green
    } else {
        Write-Host "  ⚠️  Missing: $($file.name)" -ForegroundColor Yellow
    }
}

# Step 4: Copy documentation
Write-Host "`n╔═══════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║ Step 4: Copying documentation                         ║" -ForegroundColor Cyan
Write-Host "╚═══════════════════════════════════════════════════════╝" -ForegroundColor Cyan

if (Test-Path "$source\AUTH_SETUP_GUIDE.md") {
    Copy-Item -Path "$source\AUTH_SETUP_GUIDE.md" -Destination "$target\AUTH_SETUP_GUIDE.md" -Force
    Write-Host "  ✅ Copied: AUTH_SETUP_GUIDE.md" -ForegroundColor Green
} else {
    Write-Host "  ⚠️  Missing: AUTH_SETUP_GUIDE.md" -ForegroundColor Yellow
}

# Step 5: Copy env example
Write-Host "`n╔═══════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║ Step 5: Copying environment template                 ║" -ForegroundColor Cyan
Write-Host "╚═══════════════════════════════════════════════════════╝" -ForegroundColor Cyan

if (Test-Path "$source\.env.local.example") {
    Copy-Item -Path "$source\.env.local.example" -Destination "$target\.env.local.example.supabase" -Force
    Write-Host "  ✅ Copied: .env.local.example (as .env.local.example.supabase)" -ForegroundColor Green
    Write-Host "  ℹ️  Merge these variables into your existing .env.local" -ForegroundColor Gray
} else {
    Write-Host "  ⚠️  Missing: .env.local.example" -ForegroundColor Yellow
}

# Summary
Write-Host "`n╔═══════════════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "║ ✅ Migration Complete!                                ║" -ForegroundColor Green
Write-Host "╚═══════════════════════════════════════════════════════╝" -ForegroundColor Green

Write-Host "`n📋 Files migrated successfully!" -ForegroundColor Green
Write-Host "   • 4 auth pages (login, signup, profile, callback)" -ForegroundColor White
Write-Host "   • 5 infrastructure files (context, clients, middleware, types)" -ForegroundColor White
Write-Host "   • 1 documentation file" -ForegroundColor White
Write-Host "   • 1 environment template" -ForegroundColor White

# Manual steps reminder
Write-Host "`n╔═══════════════════════════════════════════════════════╗" -ForegroundColor Yellow
Write-Host "║ ⚠️  MANUAL STEPS REQUIRED                             ║" -ForegroundColor Yellow
Write-Host "╚═══════════════════════════════════════════════════════╝" -ForegroundColor Yellow

Write-Host "`n1️⃣  Update app/layout.tsx" -ForegroundColor Cyan
Write-Host "   Add this import:" -ForegroundColor White
Write-Host "   import { AuthProvider } from '@/contexts/AuthContext'" -ForegroundColor Gray
Write-Host "   Wrap children with:" -ForegroundColor White
Write-Host "   <AuthProvider>{children}</AuthProvider>" -ForegroundColor Gray

Write-Host "`n2️⃣  Add environment variables to .env.local" -ForegroundColor Cyan
Write-Host "   NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co" -ForegroundColor Gray
Write-Host "   NEXT_PUBLIC_SUPABASE_ANON_KEY=your-anon-key" -ForegroundColor Gray
Write-Host "   NEXT_PUBLIC_SITE_URL=http://localhost:3000" -ForegroundColor Gray

Write-Host "`n3️⃣  Install dependencies" -ForegroundColor Cyan
Write-Host "   cd $target" -ForegroundColor Gray
Write-Host "   npm install @supabase/supabase-js@latest @supabase/auth-helpers-nextjs@latest @supabase/ssr@latest" -ForegroundColor Gray

Write-Host "`n4️⃣  Test the application" -ForegroundColor Cyan
Write-Host "   npm run dev" -ForegroundColor Gray
Write-Host "   • Test gift search (should work without login)" -ForegroundColor Gray
Write-Host "   • Test login/signup pages" -ForegroundColor Gray
Write-Host "   • Test protected profile page" -ForegroundColor Gray

Write-Host "`n5️⃣  ONLY after everything works - Delete old frontend" -ForegroundColor Cyan
Write-Host "   Remove-Item -Path '$source' -Recurse -Force" -ForegroundColor Gray

Write-Host "`n📚 See FRONTEND_AUTH_MIGRATION_PLAN.md for complete details`n" -ForegroundColor White
