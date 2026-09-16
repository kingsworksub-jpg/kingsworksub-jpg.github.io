#!/usr/bin/awk -f
# Generates a 5-axis radar chart as a standalone SVG (500x460 viewBox).
#
# Usage:
#   awk -v TITLE="Product Name" -v COLOR="#4C6EF5" -v SCORES="4,4,4,3,4" \
#       -v LAB0="学習コスト" -v LAB1="打ち込み" -v LAB2="制作速度" \
#       -v LAB3="拡張性" -v LAB4="安定性" \
#       -f scripts/radar-chart.awk > static/images/radar/product-slug.svg
#
# SCORES are 5 comma-separated integers 1-5, in the same order as LAB0..LAB4.
# LAB0..LAB4 are optional — default to the software-usability axis set below.
# Pick axis wording that actually fits the product category being reviewed
# (see CLAUDE.md "Evaluation axes" section) rather than reusing these
# defaults verbatim for hardware/non-software reviews.
BEGIN {
    ux[0]=0.0000;      uy[0]=-1.0000
    ux[1]=0.9511;      uy[1]=-0.3090
    ux[2]=0.5878;      uy[2]=0.8090
    ux[3]=-0.5878;     uy[3]=0.8090
    ux[4]=-0.9511;     uy[4]=-0.3090

    lab[0] = (LAB0 != "") ? LAB0 : "学習コスト"
    lab[1] = (LAB1 != "") ? LAB1 : "打ち込み"
    lab[2] = (LAB2 != "") ? LAB2 : "制作速度"
    lab[3] = (LAB3 != "") ? LAB3 : "拡張性"
    lab[4] = (LAB4 != "") ? LAB4 : "安定性"

    anchor[0]="middle"; dx0[0]=0;    dy0[0]=-10
    anchor[1]="start";  dx0[1]=10;   dy0[1]=-2
    anchor[2]="start";  dx0[2]=10;   dy0[2]=16
    anchor[3]="end";    dx0[3]=-10;  dy0[3]=16
    anchor[4]="end";    dx0[4]=-10;  dy0[4]=-2

    cx=250; cy=250; R=140; RL=178

    split(SCORES, s, ",")

    print "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 500 460\" font-family=\"'Hiragino Sans','Noto Sans JP',sans-serif\">"
    print "<rect x=\"0\" y=\"0\" width=\"500\" height=\"460\" rx=\"18\" fill=\"#F8F6F1\"/>"
    print "<text x=\"250\" y=\"32\" text-anchor=\"middle\" font-size=\"21\" font-weight=\"700\" fill=\"#3A362E\">" TITLE "</text>"

    for (L=1; L<=5; L++) {
        pts=""
        for (i=0; i<5; i++) {
            px = cx + (L/5)*R*ux[i]
            py = cy + (L/5)*R*uy[i]
            pts = pts sprintf("%.1f,%.1f ", px, py)
        }
        strokecol = (L==5) ? "#B9B4A8" : "#DDD9CF"
        print "<polygon points=\"" pts "\" fill=\"none\" stroke=\"" strokecol "\" stroke-width=\"1\"/>"
    }

    for (i=0; i<5; i++) {
        px = cx + R*ux[i]; py = cy + R*uy[i]
        print "<line x1=\"" cx "\" y1=\"" cy "\" x2=\"" px "\" y2=\"" py "\" stroke=\"#CFCABD\" stroke-width=\"1\"/>"
    }

    for (i=0; i<5; i++) {
        lx = cx + RL*ux[i]; ly = cy + RL*uy[i]
        print "<text x=\"" (lx+dx0[i]) "\" y=\"" (ly+dy0[i]) "\" text-anchor=\"" anchor[i] "\" font-size=\"15\" font-weight=\"600\" fill=\"#4A4636\">" lab[i] "</text>"
    }

    dpts=""
    for (i=0; i<5; i++) {
        val = s[i+1]
        px = cx + (val/5)*R*ux[i]
        py = cy + (val/5)*R*uy[i]
        dpts = dpts sprintf("%.1f,%.1f ", px, py)
        dxp[i]=px; dyp[i]=py
    }
    print "<polygon points=\"" dpts "\" fill=\"" COLOR "\" fill-opacity=\"0.28\" stroke=\"" COLOR "\" stroke-width=\"2.5\" stroke-linejoin=\"round\"/>"

    for (i=0; i<5; i++) {
        print "<circle cx=\"" dxp[i] "\" cy=\"" dyp[i] "\" r=\"4.5\" fill=\"" COLOR "\" stroke=\"#F8F6F1\" stroke-width=\"1.5\"/>"
    }

    print "</svg>"
}
